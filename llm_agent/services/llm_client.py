from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Iterator

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter


logger = logging.getLogger("llm_agent")

_SUPPORTED_INTERFACES = {"chat_completions", "responses"}
_INTERFACE_ALIASES = {
    "chat": "chat_completions",
    "chat_completion": "chat_completions",
    "chat_completions": "chat_completions",
    "chat-completions": "chat_completions",
    "response": "responses",
    "responses": "responses",
}
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_SESSIONS: dict[tuple[str, int], Session] = {}
_SESSIONS_LOCK = threading.Lock()


@dataclass(frozen=True)
class LLMRuntimeConfig:
    name: str = "llm"
    provider: str = "openai"
    model: str = ""
    api_base: str = ""
    api_key: str = ""
    api_interface: str = "chat_completions"
    api_interface_preference: str = "chat_completions"
    temperature: float = 0.2
    connect_timeout_sec: float = 10.0
    read_timeout_sec: float = 60.0
    stream_read_timeout_sec: float = 300.0
    max_retries: int = 2
    initial_retry_delay_sec: float = 1.0
    max_retry_delay_sec: float = 8.0
    pool_maxsize: int = 10
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, config: dict[str, Any] | None, *, name: str = "llm") -> "LLMRuntimeConfig":
        config = config or {}
        return cls(
            name=str(config.get("NAME") or name),
            provider=str(config.get("PROVIDER") or "openai"),
            model=str(config.get("MODEL") or ""),
            api_base=str(config.get("API_BASE") or ""),
            api_key=str(config.get("API_KEY") or ""),
            api_interface=normalize_interface(config.get("API_INTERFACE"), default="chat_completions"),
            api_interface_preference=normalize_interface(
                config.get("API_INTERFACE_PREFERENCE"),
                default="chat_completions",
            ),
            temperature=_safe_float(config.get("TEMPERATURE"), 0.2),
            connect_timeout_sec=_safe_float(config.get("CONNECT_TIMEOUT_SEC"), 10.0),
            read_timeout_sec=_safe_float(config.get("READ_TIMEOUT_SEC"), 60.0),
            stream_read_timeout_sec=_safe_float(config.get("STREAM_READ_TIMEOUT_SEC"), 300.0),
            max_retries=max(0, _safe_int(config.get("MAX_RETRIES"), 2)),
            initial_retry_delay_sec=max(0.1, _safe_float(config.get("INITIAL_RETRY_DELAY_SEC"), 1.0)),
            max_retry_delay_sec=max(0.1, _safe_float(config.get("MAX_RETRY_DELAY_SEC"), 8.0)),
            pool_maxsize=max(1, _safe_int(config.get("POOL_MAXSIZE"), 10)),
            extra_headers=_safe_headers(config.get("EXTRA_HEADERS")),
        )

    def is_ready(self) -> bool:
        return bool(self.api_key and self.api_base and self.model)


@dataclass
class LLMStreamEvent:
    kind: str
    delta: str = ""
    error: str = ""
    detail: str = ""
    interface: str = ""
    status_code: int | None = None
    raw: dict[str, Any] | None = None


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: str
    raw: dict[str, Any] | None = None


class LLMClientError(Exception):
    def __init__(
        self,
        code: str,
        *,
        detail: str = "",
        status_code: int | None = None,
        interface: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.interface = interface
        self.retryable = retryable


class LLMClient:
    def __init__(self, config: dict[str, Any] | LLMRuntimeConfig | None, *, name: str = "llm") -> None:
        if isinstance(config, LLMRuntimeConfig):
            self.config = config
        else:
            self.config = LLMRuntimeConfig.from_mapping(config, name=name)

    def candidate_interfaces(self) -> list[str]:
        return list(self._candidate_interfaces())

    def create_text(self, messages: Iterable[dict[str, Any]]) -> str:
        messages = list(messages)
        last_error: LLMClientError | None = None
        for interface in self._candidate_interfaces():
            try:
                payload = self._build_payload(messages, interface=interface, stream=False)
                response = self._request(payload, interface=interface, stream=False)
                data = self._read_json_response(response, interface=interface)
                return self._extract_text(data, interface=interface)
            except LLMClientError as exc:
                last_error = exc
                if self._should_fallback(exc, attempted_interface=interface):
                    self._log_fallback(exc, attempted_interface=interface)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise LLMClientError("llm_request_failed", detail="no_available_llm_interface")

    def create_raw(
        self,
        messages: Iterable[dict[str, Any]] | None = None,
        *,
        tools: Iterable[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        interface: str | None = None,
        previous_response_id: str | None = None,
        response_input: Iterable[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        messages = list(messages or [])
        response_input = list(response_input or [])
        last_error: LLMClientError | None = None
        interfaces = [interface] if interface else self._candidate_interfaces()

        for candidate_interface in interfaces:
            try:
                payload = self._build_payload(
                    messages,
                    interface=candidate_interface,
                    stream=False,
                    tools=tools,
                    tool_choice=tool_choice,
                    previous_response_id=previous_response_id,
                    response_input=response_input,
                )
                response = self._request(payload, interface=candidate_interface, stream=False)
                data = self._read_json_response(response, interface=candidate_interface)
                return candidate_interface, data
            except LLMClientError as exc:
                last_error = exc
                if interface is None and self._should_fallback(exc, attempted_interface=candidate_interface):
                    self._log_fallback(exc, attempted_interface=candidate_interface)
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise LLMClientError("llm_request_failed", detail="no_available_llm_interface")

    def extract_text_from_payload(self, payload: dict[str, Any], *, interface: str) -> str:
        return self._extract_text(payload, interface=interface)

    def extract_tool_calls(self, payload: dict[str, Any], *, interface: str) -> list[LLMToolCall]:
        if interface == "responses":
            return _extract_responses_tool_calls(payload)
        return _extract_chat_tool_calls(payload)

    def stream_text(self, messages: Iterable[dict[str, Any]]) -> Iterator[LLMStreamEvent]:
        messages = list(messages)
        last_error: LLMClientError | None = None
        response: Response | None = None
        interface_used = ""
        for interface in self._candidate_interfaces():
            try:
                payload = self._build_payload(messages, interface=interface, stream=True)
                response = self._request(payload, interface=interface, stream=True)
                interface_used = interface
                break
            except LLMClientError as exc:
                last_error = exc
                if self._should_fallback(exc, attempted_interface=interface):
                    self._log_fallback(exc, attempted_interface=interface)
                    continue
                yield self._error_event(exc, interface=interface)
                return

        if response is None:
            yield self._error_event(
                last_error or LLMClientError("llm_request_failed", detail="stream_not_opened"),
                interface=interface_used,
            )
            return

        emitted_text = False
        try:
            for event in self._iter_stream_events(response, interface=interface_used):
                if event.kind == "delta" and event.delta:
                    emitted_text = True
                yield event
        except LLMClientError as exc:
            yield self._error_event(exc, interface=interface_used)
        except requests.RequestException as exc:
            code = "llm_stream_interrupted" if emitted_text else "llm_stream_failed"
            yield LLMStreamEvent(
                kind="error",
                error=code,
                detail=_clean_error_text(str(exc)),
                interface=interface_used,
            )
        finally:
            response.close()

    def _candidate_interfaces(self) -> list[str]:
        if self.config.api_interface != "auto":
            return [self.config.api_interface]

        preferred = self.config.api_interface_preference
        if preferred not in _SUPPORTED_INTERFACES:
            preferred = "chat_completions"
        alternate = "responses" if preferred == "chat_completions" else "chat_completions"
        return [preferred, alternate]

    def _build_payload(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        interface: str,
        stream: bool,
        tools: Iterable[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        previous_response_id: str | None = None,
        response_input: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if interface == "responses":
            if previous_response_id:
                normalized_input = list(response_input or [])
                if not normalized_input:
                    raise LLMClientError(
                        "invalid_llm_messages",
                        detail="missing_response_input",
                        interface=interface,
                    )
                payload = {
                    "model": self.config.model,
                    "previous_response_id": previous_response_id,
                    "input": normalized_input,
                    "temperature": self.config.temperature,
                    "stream": stream,
                }
            else:
                normalized_messages = list(_normalize_responses_messages(messages))
                if not normalized_messages:
                    raise LLMClientError(
                        "invalid_llm_messages",
                        detail="no_valid_messages",
                        interface=interface,
                    )
                payload = {
                    "model": self.config.model,
                    "input": [
                        {
                            "type": "message",
                            "role": message["role"],
                            "content": message["content"],
                        }
                        for message in normalized_messages
                    ],
                    "temperature": self.config.temperature,
                    "stream": stream,
                }
        else:
            normalized_messages = list(_normalize_chat_messages(messages))
            if not normalized_messages:
                raise LLMClientError("invalid_llm_messages", detail="no_valid_messages", interface=interface)
            payload = {
                "model": self.config.model,
                "messages": normalized_messages,
                "temperature": self.config.temperature,
                "stream": stream,
            }
        normalized_tools = _normalize_tool_definitions(tools, interface=interface)
        if normalized_tools:
            payload["tools"] = normalized_tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    def _request(self, payload: dict[str, Any], *, interface: str, stream: bool) -> Response:
        if not self.config.is_ready():
            raise LLMClientError("invalid_llm_config", detail="missing_model_or_credentials", interface=interface)

        session = _get_session(self.config)
        url = _build_endpoint(self.config.api_base, interface)
        timeout = (
            self.config.connect_timeout_sec,
            self.config.stream_read_timeout_sec if stream else self.config.read_timeout_sec,
        )
        request_id = uuid.uuid4().hex
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "AI4MW/llm-client",
            "Idempotency-Key": request_id,
        }
        headers.update(self.config.extra_headers)

        max_attempts = self.config.max_retries + 1
        last_error: LLMClientError | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                    stream=stream,
                )
                response.encoding = "utf-8"
            except requests.Timeout as exc:
                last_error = LLMClientError(
                    "llm_request_timeout",
                    detail=_clean_error_text(str(exc)),
                    interface=interface,
                    retryable=True,
                )
                if attempt >= max_attempts:
                    raise last_error
                _sleep_before_retry(self.config, attempt)
                continue
            except requests.RequestException as exc:
                last_error = LLMClientError(
                    "llm_request_failed",
                    detail=_clean_error_text(str(exc)),
                    interface=interface,
                    retryable=True,
                )
                if attempt >= max_attempts:
                    raise last_error
                _sleep_before_retry(self.config, attempt)
                continue

            if response.status_code < 400:
                return response

            detail = _extract_error_detail(response)
            retryable = response.status_code in _RETRYABLE_STATUS_CODES
            error = LLMClientError(
                "llm_http_error",
                detail=detail,
                status_code=response.status_code,
                interface=interface,
                retryable=retryable,
            )
            response.close()
            last_error = error
            if retryable and attempt < max_attempts:
                _sleep_before_retry(
                    self.config,
                    attempt,
                    retry_after_header=response.headers.get("Retry-After"),
                )
                continue
            raise error

        if last_error is not None:
            raise last_error
        raise LLMClientError("llm_request_failed", detail="unknown_request_failure", interface=interface)

    def _read_json_response(self, response: Response, *, interface: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            response.close()
            raise LLMClientError(
                "invalid_llm_response",
                detail=_clean_error_text(str(exc)),
                interface=interface,
            ) from exc
        finally:
            response.close()

        if not isinstance(data, dict):
            raise LLMClientError(
                "invalid_llm_response",
                detail="non_object_response",
                interface=interface,
            )
        return data

    def _extract_text(self, data: dict[str, Any], *, interface: str) -> str:
        if interface == "responses":
            text = _extract_responses_text(data)
        else:
            text = _extract_chat_text(data)
        return text.strip()

    def _iter_stream_events(self, response: Response, *, interface: str) -> Iterator[LLMStreamEvent]:
        for event_name, data in _iter_sse(response):
            if not data:
                continue
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            if interface == "responses":
                stream_event = _parse_responses_stream_event(event_name, payload)
            else:
                stream_event = _parse_chat_stream_event(payload)
            if stream_event is None:
                continue
            stream_event.interface = interface
            yield stream_event

    def _should_fallback(self, error: LLMClientError, *, attempted_interface: str) -> bool:
        if self.config.api_interface != "auto":
            return False
        if attempted_interface not in _SUPPORTED_INTERFACES:
            return False
        if error.status_code in {404, 405, 415, 422, 501}:
            return True
        if error.status_code != 400:
            return False
        detail = (error.detail or "").lower()
        interface_terms = {
            "chat_completions": ["messages", "chat/completions", "chat completions"],
            "responses": ["input", "/responses", "responses api", "response api"],
        }
        for term in interface_terms.get(attempted_interface, []):
            if term in detail:
                return True
        return any(
            phrase in detail
            for phrase in (
                "unsupported",
                "not support",
                "unknown field",
                "unknown parameter",
                "unrecognized request argument",
                "invalid endpoint",
                "not found",
            )
        )

    def _log_fallback(self, error: LLMClientError, *, attempted_interface: str) -> None:
        next_interface = "responses" if attempted_interface == "chat_completions" else "chat_completions"
        logger.warning(
            "LLM_INTERFACE_FALLBACK name=%s model=%s from=%s to=%s status=%s detail=%s",
            self.config.name,
            self.config.model,
            attempted_interface,
            next_interface,
            error.status_code,
            _clean_error_text(error.detail),
        )

    def _error_event(self, error: LLMClientError, *, interface: str) -> LLMStreamEvent:
        return LLMStreamEvent(
            kind="error",
            error=error.code,
            detail=error.detail,
            interface=interface or error.interface,
            status_code=error.status_code,
        )


def normalize_interface(value: Any, *, default: str = "chat_completions") -> str:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized == "auto":
        return "auto"
    return _INTERFACE_ALIASES.get(normalized, default)


def _normalize_responses_messages(messages: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role == "system":
            role = "developer"
        if role not in {"developer", "user", "assistant"}:
            continue
        content_items = _normalize_responses_content(item.get("content"))
        if not content_items:
            continue
        yield {"role": role, "content": content_items}


def _normalize_chat_messages(messages: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()

        if role == "tool":
            content = item.get("content")
            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if isinstance(content, str) and content.strip() and tool_call_id:
                yield {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content.strip(),
                }
            continue

        if role not in {"system", "developer", "user", "assistant"}:
            continue

        content = item.get("content")
        normalized_content = _normalize_chat_content(content)
        normalized: dict[str, Any] = {"role": role, "content": normalized_content}
        tool_calls = item.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            normalized["tool_calls"] = tool_calls
        if _chat_content_is_empty(normalized_content) and "tool_calls" not in normalized:
            continue
        yield normalized


def _normalize_responses_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "input_text", "text": text}] if text else []

    if not isinstance(content, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type in {"input_text", "text"}:
            text = str(item.get("text") or "").strip()
            if text:
                normalized.append({"type": "input_text", "text": text})
            continue
        if item_type in {"input_image", "image_url"}:
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            image_url_text = str(image_url or "").strip()
            if image_url_text:
                normalized.append({"type": "input_image", "image_url": image_url_text})
    return normalized


def _normalize_chat_content(content: Any) -> Any:
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return ""

    normalized: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type in {"input_text", "text"}:
            text = str(item.get("text") or "").strip()
            if text:
                normalized.append({"type": "text", "text": text})
            continue
        if item_type in {"input_image", "image_url"}:
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            image_url_text = str(image_url or "").strip()
            if image_url_text:
                normalized.append({"type": "image_url", "image_url": {"url": image_url_text}})
    if not normalized:
        return ""
    if len(normalized) == 1 and normalized[0].get("type") == "text":
        return normalized[0].get("text", "")
    return normalized


def _chat_content_is_empty(content: Any) -> bool:
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        return len(content) == 0
    return True


def _normalize_tool_definitions(
    tools: Iterable[dict[str, Any]] | None,
    *,
    interface: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type") or "function").strip() or "function"
        if tool_type != "function":
            continue
        if interface == "chat_completions" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(function.get("description") or "").strip(),
                        "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
            )
            continue

        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        description = str(tool.get("description") or "").strip()
        parameters = tool.get("parameters") or {"type": "object", "properties": {}}
        if interface == "responses":
            normalized.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
            )
        else:
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
    return normalized


def _build_endpoint(api_base: str, interface: str) -> str:
    base = (api_base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        if interface == "chat_completions":
            return base
        base = base[: -len("/chat/completions")]
    elif base.endswith("/responses"):
        if interface == "responses":
            return base
        base = base[: -len("/responses")]

    suffix = "/chat/completions" if interface == "chat_completions" else "/responses"
    if base.endswith("/v1"):
        return f"{base}{suffix}"
    return f"{base}/v1{suffix}"


def _get_session(config: LLMRuntimeConfig) -> Session:
    key = (config.api_base.rstrip("/"), config.pool_maxsize)
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(key)
        if session is not None:
            return session
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=config.pool_maxsize,
            pool_maxsize=config.pool_maxsize,
            max_retries=0,
            pool_block=True,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _SESSIONS[key] = session
        return session


def _iter_sse(response: Response) -> Iterator[tuple[str, str]]:
    event_name = ""
    data_lines: list[str] = []
    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore")
        line = line.rstrip("\r")
        if not line:
            if event_name or data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)
    if event_name or data_lines:
        yield event_name, "\n".join(data_lines)


def _parse_chat_stream_event(payload: dict[str, Any]) -> LLMStreamEvent | None:
    if "error" in payload:
        detail = _clean_error_text(json.dumps(payload.get("error"), ensure_ascii=False))
        return LLMStreamEvent(kind="error", error="llm_http_error", detail=detail, raw=payload)
    choices = payload.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return None
    delta = _extract_text_value((choices[0] or {}).get("delta", {}).get("content", ""))
    if not delta:
        return None
    return LLMStreamEvent(kind="delta", delta=delta, raw=payload)


def _parse_responses_stream_event(event_name: str, payload: dict[str, Any]) -> LLMStreamEvent | None:
    event_type = str(payload.get("type") or event_name or "")
    if event_type == "error":
        detail = _clean_error_text(_stringify_error_payload(payload))
        return LLMStreamEvent(kind="error", error="llm_http_error", detail=detail, raw=payload)
    if event_type == "response.output_text.delta":
        delta = str(payload.get("delta") or "")
        if delta:
            return LLMStreamEvent(kind="delta", delta=delta, raw=payload)
    return None


def _extract_chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return _extract_text_value(message.get("content", ""))


def _extract_responses_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
    if texts:
        return "".join(texts)
    return _extract_text_value(payload.get("output_text", ""))


def _extract_chat_tool_calls(payload: dict[str, Any]) -> list[LLMToolCall]:
    choices = payload.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return []
    message = (choices[0] or {}).get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        return []

    normalized: list[LLMToolCall] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        name = str(function.get("name") or "").strip()
        call_id = str(item.get("id") or "").strip()
        arguments = function.get("arguments") or ""
        if not name or not call_id or not isinstance(arguments, str):
            continue
        normalized.append(
            LLMToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                raw=item,
            )
        )
    return normalized


def _extract_responses_tool_calls(payload: dict[str, Any]) -> list[LLMToolCall]:
    normalized: list[LLMToolCall] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        call_id = str(item.get("call_id") or item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        arguments = item.get("arguments") or ""
        if not name or not call_id or not isinstance(arguments, str):
            continue
        normalized.append(
            LLMToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                raw=item,
            )
        )
    return normalized


def _extract_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
                continue
            delta = item.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
        return "".join(parts)
    return ""


def _extract_error_detail(response: Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    return _clean_error_text(_stringify_error_payload(payload))


def _stringify_error_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or error.get("type")
            if isinstance(message, str) and message:
                return message
            return json.dumps(error, ensure_ascii=False)
        if isinstance(error, str):
            return error
        message = payload.get("message") or payload.get("detail")
        if isinstance(message, str) and message:
            return message
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, str):
        return payload
    return str(payload)


def _sleep_before_retry(
    config: LLMRuntimeConfig,
    attempt: int,
    *,
    retry_after_header: str | None = None,
) -> None:
    retry_after = _parse_retry_after(retry_after_header)
    if retry_after is not None:
        delay = retry_after
    else:
        delay = min(
            config.max_retry_delay_sec,
            config.initial_retry_delay_sec * (2 ** max(0, attempt - 1)),
        )
        delay = delay * random.uniform(0.8, 1.2)
    time.sleep(max(0.0, min(delay, config.max_retry_delay_sec)))


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def _clean_error_text(text: str, *, limit: int = 1000) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    headers: dict[str, str] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        value_text = str(item).strip()
        if key_text and value_text:
            headers[key_text] = value_text
    return headers
