from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import httpx

from .config import AgentConfig


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL)


@dataclass(slots=True)
class CompletionUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class CompletionResult:
    payload: dict[str, Any]
    usage: CompletionUsage


class OpenRouterClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.openrouter_api_base,
            timeout=config.http_timeout_seconds,
            limits=httpx.Limits(
                max_keepalive_connections=config.max_concurrency,
                max_connections=config.max_concurrency,
            ),
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local-fss-agent",
                "X-Title": "fss-extraction-agent",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_json_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> CompletionResult:
        last_error: JSONDecodeError | None = None
        for attempt in range(3):
            current_max_tokens = max_tokens * (attempt + 1)
            payload = {
                "model": model,
                "messages": messages,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "max_tokens": current_max_tokens,
                "response_format": {"type": "json_object"},
            }
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage_data = data.get("usage", {}) or {}
            usage = CompletionUsage(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_data.get("total_tokens", 0) or 0),
            )
            try:
                return CompletionResult(payload=self._parse_json_content(content), usage=usage)
            except JSONDecodeError as exc:
                last_error = exc
        raise ValueError("Model returned invalid or truncated JSON after retries.") from last_error

    @staticmethod
    def _parse_json_content(content: Any) -> dict[str, Any]:
        if isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = str(content)

        text = text.strip()
        match = JSON_BLOCK_RE.search(text)
        if match:
            text = match.group(1).strip()

        return json.loads(text)
