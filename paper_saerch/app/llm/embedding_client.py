from __future__ import annotations

import asyncio

import requests



class EmbeddingClient:
    def __init__(self) -> None:
        self.settings = self._resolve_runtime_config()
        self.timeout = float(self.settings.get("READ_TIMEOUT_SEC", 60) or 60)
        self.connect_timeout = float(self.settings.get("CONNECT_TIMEOUT_SEC", 10) or 10)
        self.batch_size = max(1, int(self.settings.get("BATCH_SIZE", 10) or 10))

    def is_configured(self) -> bool:
        return bool(
            self.settings.get("API_KEY")
            and self.settings.get("API_BASE")
            and self.settings.get("MODEL")
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.is_configured():
            raise RuntimeError("Embedding client is not configured")

        cleaned = [(text or " ").strip() or " " for text in texts]
        vectors: list[list[float]] = []

        for idx in range(0, len(cleaned), self.batch_size):
            batch = cleaned[idx : idx + self.batch_size]
            payload = await asyncio.to_thread(self._embed_batch_sync, batch)
            data = payload.get("data", [])
            vectors.extend([item.get("embedding", []) for item in data])

        if len(vectors) != len(cleaned):
            raise RuntimeError("Embedding response size mismatch")

        return vectors

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings['API_KEY']}",
            "Content-Type": "application/json",
        }

    def _embed_batch_sync(self, batch: list[str]) -> dict:
        response = requests.post(
            f"{self.settings['API_BASE'].rstrip('/')}/embeddings",
            headers=self._headers(),
            json={
                "model": self.settings["MODEL"],
                "input": batch,
            },
            timeout=(self.connect_timeout, self.timeout),
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _resolve_runtime_config(self) -> dict[str, object]:
        try:
            from django.conf import settings as django_settings

            if getattr(django_settings, "configured", False):
                return dict(getattr(django_settings, "EMBED_CONFIG", {}))
        except Exception:
            pass

        from paper_saerch.config import get_settings

        raw_settings = get_settings().get("embedding", {})
        return {
            "MODEL": raw_settings.get("model", ""),
            "API_BASE": raw_settings.get("api_base", ""),
            "API_KEY": raw_settings.get("api_key", ""),
            "CONNECT_TIMEOUT_SEC": raw_settings.get("request_timeout_seconds", 60),
            "READ_TIMEOUT_SEC": raw_settings.get("request_timeout_seconds", 60),
            "BATCH_SIZE": raw_settings.get("batch_size", 10),
        }
