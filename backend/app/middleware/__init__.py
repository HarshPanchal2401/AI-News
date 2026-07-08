"""
AI Pulse – Middleware Stack
==============================
Rate limiting, auth, logging, and CORS middleware.
"""

from __future__ import annotations

import time
import uuid as uuid_module
from typing import Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.exceptions import AppException, RateLimitError
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Logging Middleware ─────────────────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request/response with timing, trace IDs, and status codes.
    Adds X-Request-ID header to each response.
    """

    SKIP_PATHS = {"/health", "/metrics"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate a unique trace ID for this request
        trace_id = str(uuid_module.uuid4())
        request.state.trace_id = trace_id

        # Bind context to all logs within this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )

        start_time = time.perf_counter()

        if request.url.path not in self.SKIP_PATHS:
            logger.info("request_started")

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        if request.url.path not in self.SKIP_PATHS:
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        response.headers["X-Request-ID"] = trace_id
        response.headers["X-Process-Time"] = str(duration_ms)

        return response


# ── Rate Limiting Middleware ───────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter using Upstash Redis.

    Limits:
    - Authenticated: 100 req/min
    - Anonymous: 20 req/min

    Returns 429 with Retry-After header when limit is exceeded.
    """

    SKIP_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if settings.is_development or settings.is_testing or request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        from app.services.cache.redis_client import get_redis_client

        redis = get_redis_client()

        # Identify the client
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            identifier = f"auth:{auth_header[7:40]}"  # First 33 chars of token
            limit = settings.rate_limit_per_minute_authenticated
        else:
            client_ip = request.client.host if request.client else "anonymous"
            identifier = f"ip:{client_ip}"
            limit = settings.rate_limit_per_minute_anonymous

        redis_key = f"rate_limit:{identifier}"

        # Increment counter
        count = await redis.incr(redis_key)

        # Set expiry on first request in the window
        if count == 1:
            await redis.expire(redis_key, 60)

        # Add rate limit headers
        response = None

        if count > limit:
            ttl = await redis.ttl(redis_key)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests. Please slow down.",
                    "retry_after": max(ttl, 1),
                },
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(max(ttl, 1)),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))

        return response


# ── Exception Handler Middleware ───────────────────────────────────────────────

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Convert AppException subclasses to structured JSON responses."""
    logger.warning(
        "app_exception",
        error_code=exc.error_code,
        message=exc.message,
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=str(request.url.path),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred. Please try again.",
        },
    )


# ── Middleware Registration ────────────────────────────────────────────────────

def register_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI application."""

    # CORS (must be first)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # Exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
