from __future__ import annotations

from typing import Any

import redis.asyncio as redis

from app.config import get_settings

_redis: redis.Redis | None = None


async def connect_redis() -> redis.Redis | None:
    global _redis
    try:
        _redis = redis.from_url(get_settings().redis_url, decode_responses=True)
        await _redis.ping()
        return _redis
    except Exception:
        _redis = None
        return None


async def disconnect_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def get_redis() -> redis.Redis | None:
    return _redis


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    if _redis is None:
        return
    await _redis.set(key, value, ex=ttl)


async def cache_get(key: str) -> str | None:
    if _redis is None:
        return None
    return await _redis.get(key)


async def cache_set_nx(key: str, value: str, ttl: int = 86400) -> bool:
    if _redis is None:
        return True
    return bool(await _redis.set(key, value, ex=ttl, nx=True))


async def acquire_lock(key: str, ttl: int = 30) -> bool:
    if _redis is None:
        return True
    return bool(await _redis.set(f"lock:{key}", "1", ex=ttl, nx=True))


async def release_lock(key: str) -> None:
    if _redis is None:
        return
    await _redis.delete(f"lock:{key}")
