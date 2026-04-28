from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from redis.exceptions import RedisError

from paper_saerch.app.domain.schemas import PaperResult
from paper_saerch.app.services.redis_runtime import build_redis_key, get_json_value, get_redis_client, set_json_value


_LOCAL_RATE_LOCKS: dict[str, asyncio.Lock] = {}
_LOCAL_LAST_REQUEST_AT: dict[str, float] = {}


@dataclass(slots=True)
class ProviderRuntimePolicy:
    batch_mode: str = "concurrent"
    cache_backend: str = "none"
    cache_ttl_seconds: int = 0
    rate_limit_backend: str = "none"
    min_interval_seconds: float = 0.0
    serialize_requests: bool = False
    lock_timeout_seconds: int = 45
    blocking_timeout_seconds: int = 90
    enable_local_fallback: bool = True
    retry_on_statuses: tuple[int, ...] = (429,)
    retry_backoff_seconds: float = 0.0


class ProviderRuntime:
    def __init__(self, provider_name: str, settings: dict[str, Any], http_settings: dict[str, Any]):
        self.provider_name = provider_name
        self.settings = settings
        self.http_settings = http_settings
        runtime_settings = settings.get("runtime", {})
        runtime = runtime_settings if isinstance(runtime_settings, dict) else {}

        retry_on_statuses = runtime.get("retry_on_statuses", [429])
        if not isinstance(retry_on_statuses, list):
            retry_on_statuses = [429]

        self.policy = ProviderRuntimePolicy(
            batch_mode=str(runtime.get("batch_mode", "concurrent")).lower(),
            cache_backend=str(runtime.get("cache_backend", "none")).lower(),
            cache_ttl_seconds=max(0, int(runtime.get("cache_ttl_seconds", 0) or 0)),
            rate_limit_backend=str(runtime.get("rate_limit_backend", "none")).lower(),
            min_interval_seconds=float(
                runtime.get("min_interval_seconds", settings.get("request_interval_seconds", 0.0)) or 0.0
            ),
            serialize_requests=bool(
                runtime.get(
                    "serialize_requests",
                    bool(int(settings.get("max_concurrent_requests", 0) or 0) == 1),
                )
            ),
            lock_timeout_seconds=max(1, int(runtime.get("lock_timeout_seconds", 45) or 45)),
            blocking_timeout_seconds=max(1, int(runtime.get("blocking_timeout_seconds", 90) or 90)),
            enable_local_fallback=bool(runtime.get("enable_local_fallback", True)),
            retry_on_statuses=tuple(
                int(status) for status in retry_on_statuses if str(status).strip().isdigit()
            )
            or (429,),
            retry_backoff_seconds=float(runtime.get("retry_backoff_seconds", 0.0) or 0.0),
        )

    async def batch_results(
        self,
        items: list[Any],
        limit: int,
        search_fn: Callable[[Any, int], Awaitable[list[PaperResult]]],
    ) -> list[PaperResult]:
        if self.policy.batch_mode == "sequential":
            results: list[PaperResult] = []
            for item in items:
                try:
                    results.extend(await search_fn(item, limit))
                except Exception:
                    continue
            return results

        gathered = await asyncio.gather(
            *(search_fn(item, limit) for item in items),
            return_exceptions=True,
        )
        results: list[PaperResult] = []
        for payload in gathered:
            if isinstance(payload, Exception):
                continue
            results.extend(payload)
        return results

    async def run_results_operation(
        self,
        operation: str,
        cache_payload: dict[str, Any],
        producer: Callable[[], Awaitable[list[PaperResult]]],
    ) -> list[PaperResult]:
        cached_results = await self._load_cached_results(operation, cache_payload)
        if cached_results is not None:
            return cached_results

        results = await producer()
        await self._store_cached_results(operation, cache_payload, results)
        return results

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        max_retries = max(0, int(self.http_settings.get("max_retries", 1) or 1))
        response: httpx.Response | None = None
        for attempt in range(max_retries + 1):
            response = await self._perform_request(client, method, url, params=params, headers=headers)
            if response.status_code not in self.policy.retry_on_statuses or attempt >= max_retries:
                return response

            retry_delay = self._resolve_retry_delay(response)
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)

        if response is None:
            raise RuntimeError(f"{self.provider_name} request failed before receiving a response")
        return response

    async def _perform_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self.policy.rate_limit_backend == "none":
            return await client.request(method, url, params=params, headers=headers)

        if not self._requires_request_control():
            return await client.request(method, url, params=params, headers=headers)

        redis_client = await get_redis_client()
        if redis_client is not None and self.policy.rate_limit_backend == "redis":
            return await self._perform_redis_rate_limited_request(
                redis_client,
                client,
                method,
                url,
                params=params,
                headers=headers,
            )

        if self.policy.rate_limit_backend == "local" or self.policy.enable_local_fallback:
            return await self._perform_local_rate_limited_request(
                client,
                method,
                url,
                params=params,
                headers=headers,
            )

        return await client.request(method, url, params=params, headers=headers)

    def _requires_request_control(self) -> bool:
        return self.policy.serialize_requests or self.policy.min_interval_seconds > 0.0

    async def _perform_redis_rate_limited_request(
        self,
        redis_client,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        lock = redis_client.lock(
            self._lock_key(),
            timeout=self.policy.lock_timeout_seconds,
            blocking_timeout=self.policy.blocking_timeout_seconds,
            sleep=0.1,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise RuntimeError(f"failed to acquire distributed lock for provider={self.provider_name}")

        request_sent = False
        try:
            if self.policy.min_interval_seconds > 0:
                last_request_raw = await redis_client.get(self._last_request_key())
                now = await self._redis_now(redis_client)
                if last_request_raw:
                    elapsed = max(0.0, now - float(last_request_raw))
                    if elapsed < self.policy.min_interval_seconds:
                        await asyncio.sleep(self.policy.min_interval_seconds - elapsed)

            response = await client.request(method, url, params=params, headers=headers)
            request_sent = True
            return response
        finally:
            if request_sent and self.policy.min_interval_seconds > 0:
                try:
                    await redis_client.set(
                        self._last_request_key(),
                        f"{await self._redis_now(redis_client):.6f}",
                        ex=max(self.policy.lock_timeout_seconds * 2, 60),
                    )
                except RedisError:
                    pass
            try:
                await lock.release()
            except Exception:
                pass

    async def _perform_local_rate_limited_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        provider_lock = _LOCAL_RATE_LOCKS.setdefault(self.provider_name, asyncio.Lock())
        request_sent = False
        async with provider_lock:
            try:
                if self.policy.min_interval_seconds > 0:
                    last_request_at = _LOCAL_LAST_REQUEST_AT.get(self.provider_name, 0.0)
                    elapsed = max(0.0, time.time() - last_request_at)
                    if last_request_at and elapsed < self.policy.min_interval_seconds:
                        await asyncio.sleep(self.policy.min_interval_seconds - elapsed)

                response = await client.request(method, url, params=params, headers=headers)
                request_sent = True
                return response
            finally:
                if request_sent and self.policy.min_interval_seconds > 0:
                    _LOCAL_LAST_REQUEST_AT[self.provider_name] = time.time()

    async def _load_cached_results(
        self,
        operation: str,
        cache_payload: dict[str, Any],
    ) -> list[PaperResult] | None:
        if self.policy.cache_backend != "redis" or self.policy.cache_ttl_seconds <= 0:
            return None

        cached_payload = await get_json_value(self._cache_key(operation, cache_payload))
        if not isinstance(cached_payload, dict):
            return None

        items = cached_payload.get("results")
        if not isinstance(items, list):
            return None

        try:
            return [PaperResult(**item) for item in items if isinstance(item, dict)]
        except Exception:
            return None

    async def _store_cached_results(
        self,
        operation: str,
        cache_payload: dict[str, Any],
        results: list[PaperResult],
    ) -> None:
        if self.policy.cache_backend != "redis" or self.policy.cache_ttl_seconds <= 0:
            return

        payload = {
            "results": [result.model_dump(mode="json") for result in results],
        }
        await set_json_value(
            self._cache_key(operation, cache_payload),
            payload,
            ttl_seconds=self.policy.cache_ttl_seconds,
        )

    def _cache_key(self, operation: str, cache_payload: dict[str, Any]) -> str:
        payload_digest = hashlib.sha256(
            json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return build_redis_key("providers", self.provider_name, operation, payload_digest)

    def _lock_key(self) -> str:
        return build_redis_key("providers", self.provider_name, "rate_limit_lock")

    def _last_request_key(self) -> str:
        return build_redis_key("providers", self.provider_name, "last_request_at")

    async def _redis_now(self, redis_client) -> float:
        seconds, microseconds = await redis_client.time()
        return float(seconds) + float(microseconds) / 1_000_000.0

    def _resolve_retry_delay(self, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return max(float(retry_after), self.policy.min_interval_seconds, self.policy.retry_backoff_seconds)
        return max(self.policy.min_interval_seconds, self.policy.retry_backoff_seconds)
