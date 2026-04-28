from __future__ import annotations

import asyncio
import json
from typing import Any

from llm_agent.services.llm_client import LLMClient as UnifiedLLMClient


class LLMClient:
    def __init__(self) -> None:
        self.settings = self._resolve_runtime_config()
        self.client = UnifiedLLMClient(self.settings, name="paper_search")

    def is_configured(self) -> bool:
        return self.client.config.is_ready()

    def preferred_interface(self) -> str:
        return self.client.config.api_interface

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.is_configured():
            raise RuntimeError("LLM client is not configured")
        return await asyncio.to_thread(self._complete_json_sync, system_prompt, user_prompt)

    def _complete_json_sync(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        text = self.client.create_text(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return self._parse_json_text(text)

    def _parse_json_text(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("LLM returned empty content")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _resolve_runtime_config(self) -> dict[str, Any]:
        try:
            from django.conf import settings as django_settings

            if getattr(django_settings, "configured", False):
                return dict(getattr(django_settings, "PAPER_SEARCH_LLM_CONFIG", {}))
        except Exception:
            pass

        from paper_saerch.config import get_settings

        raw_settings = get_settings().get("llm", {})
        return {
            "NAME": "paper_search",
            "PROVIDER": raw_settings.get("provider", "openai"),
            "MODEL": raw_settings.get("model", ""),
            "API_BASE": raw_settings.get("api_base", ""),
            "API_KEY": raw_settings.get("api_key", ""),
            "API_INTERFACE": raw_settings.get("api_interface", "chat_completions"),
            "API_INTERFACE_PREFERENCE": raw_settings.get("api_interface_preference", "chat_completions"),
            "TEMPERATURE": raw_settings.get("temperature", 0.2),
            "CONNECT_TIMEOUT_SEC": raw_settings.get("request_timeout_seconds", 60),
            "READ_TIMEOUT_SEC": raw_settings.get("request_timeout_seconds", 60),
            "STREAM_READ_TIMEOUT_SEC": raw_settings.get("request_timeout_seconds", 60),
            "MAX_RETRIES": 2,
            "INITIAL_RETRY_DELAY_SEC": 1.0,
            "MAX_RETRY_DELAY_SEC": 8.0,
            "POOL_MAXSIZE": 10,
            "EXTRA_HEADERS": {},
        }
