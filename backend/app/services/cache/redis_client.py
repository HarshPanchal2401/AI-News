"""
AI Pulse – Upstash Redis Cache Client
========================================
HTTP-based Redis client for Upstash (no persistent connection needed).
Supports TTL-based caching with a decorator pattern.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable, TypeVar

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable)


class RedisClient:
    """
    Upstash Redis REST API client.
    Uses HTTP requests — no socket connection required.
    Works perfectly in serverless/Render environments.
    """

    def __init__(self) -> None:
        self._url = settings.upstash_redis_rest_url
        self._token = settings.upstash_redis_rest_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(self, *command_parts: str | int) -> Any:
        """Execute a Redis command via REST API."""
        import httpx

        url = self._url
        # Build URL path from command parts
        path = "/".join(str(p) for p in command_parts)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{url}/{path}",
                    headers=self._headers,
                )
                data = response.json()
                return data.get("result")
        except Exception as exc:
            logger.warning("redis_request_failed", command=command_parts[0], error=str(exc))
            return None

    async def get(self, key: str) -> Any | None:
        """
        Get a cached value by key.

        Returns:
            Deserialized Python value, or None if not found.
        """
        result = await self._request("GET", key)
        if result is None:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set a cached value with optional TTL.

        Args:
            key: Cache key.
            value: Value to cache (will be JSON-serialized).
            ttl_seconds: Time-to-live in seconds.

        Returns:
            True on success.
        """
        import httpx

        serialized = json.dumps(value, default=str)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if ttl_seconds:
                    # SET key value EX ttl
                    response = await client.post(
                        f"{self._url}/set/{key}/{serialized}/EX/{ttl_seconds}",
                        headers=self._headers,
                    )
                else:
                    response = await client.post(
                        f"{self._url}/set/{key}/{serialized}",
                        headers=self._headers,
                    )
                return response.status_code == 200
        except Exception as exc:
            logger.warning("redis_set_failed", key=key, error=str(exc))
            return False

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns number of deleted keys."""
        import httpx

        try:
            key_path = "/".join(keys)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self._url}/del/{key_path}",
                    headers=self._headers,
                )
                data = response.json()
                return data.get("result", 0)
        except Exception as exc:
            logger.warning("redis_delete_failed", keys=keys, error=str(exc))
            return 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        result = await self._request("EXISTS", key)
        return bool(result)

    async def ttl(self, key: str) -> int:
        """Get remaining TTL in seconds. -1 = no TTL, -2 = not found."""
        result = await self._request("TTL", key)
        return int(result) if result is not None else -2

    async def ping(self) -> bool:
        """Health check — returns True if Redis is reachable."""
        result = await self._request("PING")
        return result == "PONG"

    async def incr(self, key: str) -> int:
        """Increment an integer value."""
        result = await self._request("INCR", key)
        return int(result) if result is not None else 0

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        """Set expiry on an existing key."""
        result = await self._request("EXPIRE", key, str(ttl_seconds))
        return bool(result)

    # ── Cache Key Builders ─────────────────────────────────────────────────────

    @staticmethod
    def key_news_latest(page: int = 1, limit: int = 20) -> str:
        return f"news:latest:p{page}:l{limit}"

    @staticmethod
    def key_news_detail(article_id: str) -> str:
        return f"news:detail:{article_id}"

    @staticmethod
    def key_brief_today(user_id: str) -> str:
        return f"brief:today:{user_id}"

    @staticmethod
    def key_categories() -> str:
        return "categories:all"

    @staticmethod
    def key_rate_limit(identifier: str) -> str:
        return f"rate_limit:{identifier}"


# Singleton
_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    """Get or create the singleton Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


def cache(ttl: int, key_fn: Callable | None = None):
    """
    Decorator for caching async function results in Redis.

    Usage:
        @cache(ttl=300, key_fn=lambda article_id: f"news:{article_id}")
        async def get_article(article_id: str) -> dict:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            redis = get_redis_client()

            # Build cache key
            if key_fn:
                cache_key = key_fn(*args, **kwargs)
            else:
                arg_str = ":".join(str(a) for a in args)
                kwarg_str = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"cache:{func.__name__}:{arg_str}:{kwarg_str}"

            # Try cache hit
            cached = await redis.get(cache_key)
            if cached is not None:
                logger.debug("cache_hit", key=cache_key, fn=func.__name__)
                return cached

            # Cache miss — execute function
            result = await func(*args, **kwargs)

            # Store in cache
            if result is not None:
                await redis.set(cache_key, result, ttl_seconds=ttl)
                logger.debug("cache_set", key=cache_key, ttl=ttl, fn=func.__name__)

            return result

        return wrapper  # type: ignore

    return decorator
