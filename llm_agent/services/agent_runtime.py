from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm_client import LLMClient, LLMClientError, LLMToolCall
from ..skills.base import SkillExecutionContext
from ..skills.registry import select_skill_context_for_tools
from ..tools.registry import ToolRegistry, build_tool_registry


_MAX_TOOL_RESULT_CHARS = 120_000


@dataclass
class AgentRunResult:
    text: str
    interface: str
    tool_calls: list[str] = field(default_factory=list)


class AgentRuntime:
    def __init__(
        self,
        llm_config: dict[str, Any],
        *,
        max_tool_rounds: int = 4,
        skill_context: SkillExecutionContext | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_result_chars: int = _MAX_TOOL_RESULT_CHARS,
    ) -> None:
        self.client = LLMClient(llm_config, name="chat-agent")
        self.max_tool_rounds = max_tool_rounds
        self.skill_context = skill_context
        self.tool_registry = tool_registry or build_tool_registry()
        self.max_tool_result_chars = max_tool_result_chars

    def run(self, messages: list[dict[str, Any]]) -> AgentRunResult:
        tools = self.tool_registry.get_definitions()
        tool_choice = "auto" if tools else None
        try:
            interface, payload = self.client.create_raw(
                messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        except LLMClientError as exc:
            if _looks_like_tools_unsupported(exc):
                text = self.client.create_text(messages)
                return AgentRunResult(
                    text=text,
                    interface=self.client.candidate_interfaces()[0],
                    tool_calls=[],
                )
            raise

        if interface == "responses":
            return self._run_responses(
                payload=payload,
                tools=tools,
            )
        return self._run_chat(
            messages=messages,
            payload=payload,
            tools=tools,
        )

    def _run_responses(
        self,
        *,
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> AgentRunResult:
        executed_calls: list[str] = []
        current_payload = payload
        loaded_skill_bundles: set[str] = set()

        for _ in range(self.max_tool_rounds + 1):
            tool_calls = self.client.extract_tool_calls(current_payload, interface="responses")
            if not tool_calls:
                text = self.client.extract_text_from_payload(current_payload, interface="responses")
                return AgentRunResult(text=text, interface="responses", tool_calls=executed_calls)

            response_id = str(current_payload.get("id") or "").strip()
            if not response_id:
                raise LLMClientError("invalid_llm_response", detail="missing_response_id", interface="responses")

            response_input = []
            selected_skill_context, loaded_now = select_skill_context_for_tools(
                [tool_call.name for tool_call in tool_calls],
                loaded_bundle_names=loaded_skill_bundles,
            )
            loaded_skill_bundles.update(loaded_now)
            if selected_skill_context:
                response_input.append(
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": selected_skill_context}],
                    }
                )
            for tool_call in tool_calls:
                executed_calls.append(tool_call.name)
                arguments = _parse_tool_arguments(tool_call)
                result = self.tool_registry.execute(tool_call.name, arguments, self.skill_context)
                response_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.id,
                        "output": _serialize_tool_result(result, self.max_tool_result_chars),
                    }
                )

            _, current_payload = self.client.create_raw(
                [],
                tools=tools,
                tool_choice="auto" if tools else None,
                interface="responses",
                previous_response_id=response_id,
                response_input=response_input,
            )

        raise LLMClientError(
            "llm_tool_loop_exceeded",
            detail="responses_tool_round_limit_exceeded",
            interface="responses",
        )

    def _run_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> AgentRunResult:
        executed_calls: list[str] = []
        current_payload = payload
        conversation_messages = list(messages)
        loaded_skill_bundles: set[str] = set()

        for _ in range(self.max_tool_rounds + 1):
            tool_calls = self.client.extract_tool_calls(current_payload, interface="chat_completions")
            if not tool_calls:
                text = self.client.extract_text_from_payload(current_payload, interface="chat_completions")
                return AgentRunResult(text=text, interface="chat_completions", tool_calls=executed_calls)

            assistant_message = _extract_chat_assistant_message(current_payload)
            conversation_messages.append(assistant_message)

            for tool_call in tool_calls:
                executed_calls.append(tool_call.name)
                arguments = _parse_tool_arguments(tool_call)
                result = self.tool_registry.execute(tool_call.name, arguments, self.skill_context)
                conversation_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": _serialize_tool_result(result, self.max_tool_result_chars),
                    }
                )

            selected_skill_context, loaded_now = select_skill_context_for_tools(
                [tool_call.name for tool_call in tool_calls],
                loaded_bundle_names=loaded_skill_bundles,
            )
            loaded_skill_bundles.update(loaded_now)
            if selected_skill_context:
                conversation_messages.append({"role": "developer", "content": selected_skill_context})

            _, current_payload = self.client.create_raw(
                conversation_messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                interface="chat_completions",
            )

        raise LLMClientError(
            "llm_tool_loop_exceeded",
            detail="chat_tool_round_limit_exceeded",
            interface="chat_completions",
        )


def _parse_tool_arguments(tool_call: LLMToolCall) -> dict[str, Any]:
    raw = (tool_call.arguments or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw_arguments": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _serialize_tool_result(result: dict[str, Any], max_chars: int) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = json.dumps({"ok": False, "error": "non_serializable_tool_result"}, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    payload = {
        "ok": result.get("ok") if isinstance(result, dict) else False,
        "tool": result.get("tool") if isinstance(result, dict) else "",
        "truncated": True,
        "result_preview": text[: max(0, max_chars - 200)],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _extract_chat_assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    message = (choices[0] or {}).get("message") if isinstance(choices, list) and choices else {}
    if not isinstance(message, dict):
        return {"role": "assistant", "content": ""}

    from .llm_client import _extract_text_value  # local import to avoid circular churn in type checking

    text = _extract_text_value(message.get("content", ""))
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    assistant_message = {"role": "assistant", "content": text}
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    return assistant_message


def _looks_like_tools_unsupported(error: LLMClientError) -> bool:
    detail = (error.detail or "").lower()
    return any(
        phrase in detail
        for phrase in (
            "tool",
            "tools",
            "function",
            "tool_choice",
            "function_call",
            "unsupported parameter",
            "unknown parameter",
            "unrecognized request argument",
        )
    )
