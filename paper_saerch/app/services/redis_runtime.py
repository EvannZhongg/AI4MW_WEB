from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from paper_saerch.config import get_settings


_REDIS_CLIENT: Redis | None = None
_REDIS_CLIENT_LOCK = asyncio.Lock()


def get_redis_settings() -> dict[str, Any]:
    settings = get_settings().get("redis", {})
    return settings if isinstance(settings, dict) else {}


def redis_enabled() -> bool:
    return bool(get_redis_settings().get("enabled", False))


def build_redis_key(*parts: object) -> str:
    prefix = str(get_redis_settings().get("key_prefix", "paper_search_agent")).strip(": ")
    key_parts = [prefix] if prefix else []
    key_parts.extend(str(part).strip(": ") for part in parts if str(part).strip(": "))
    return ":".join(key_parts)


async def get_redis_client() -> Redis | None:
    if not redis_enabled():
        return None

    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    async with _REDIS_CLIENT_LOCK:
        if _REDIS_CLIENT is not None:
            return _REDIS_CLIENT

        settings = get_redis_settings()
        client = Redis(
            host=settings.get("host", "127.0.0.1"),
            port=int(settings.get("port", 6379) or 6379),
            db=int(settings.get("db", 0) or 0),
            username=settings.get("username") or None,
            password=settings.get("password") or None,
            decode_responses=True,
            socket_connect_timeout=float(settings.get("connect_timeout_seconds", 5) or 5),
            socket_timeout=float(settings.get("socket_timeout_seconds", 5) or 5),
            health_check_interval=int(settings.get("health_check_interval_seconds", 30) or 30),
        )

        try:
            await client.ping()
        except RedisError:
            await client.aclose()
            return None

        _REDIS_CLIENT = client
        return _REDIS_CLIENT


async def close_redis_client() -> None:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        return

    await _REDIS_CLIENT.aclose()
    _REDIS_CLIENT = None


async def get_json_value(key: str) -> Any | None:
    client = await get_redis_client()
    if client is None:
        return None

    try:
        payload = await client.get(key)
    except RedisError:
        return None

    if not payload:
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


async def set_json_value(key: str, payload: Any, ttl_seconds: int | None = None) -> bool:
    client = await get_redis_client()
    if client is None:
        return False

    try:
        await client.set(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), ex=ttl_seconds)
    except (RedisError, TypeError, ValueError):
        return False
    return True
