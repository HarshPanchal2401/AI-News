"""
AI Pulse – FastAPI Application Entry Point
============================================
Creates and configures the FastAPI application with all routers,
middleware, exception handlers, and lifecycle management.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import settings
from app.core.logging import get_logger, setup_logging

# Setup logging before anything else
setup_logging(
    log_level=settings.log_level,
    is_production=settings.is_production,
)

logger = get_logger(__name__)


# ── Lifespan Manager ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages application startup and shutdown events.

    Startup:
    - Verify database connection
    - Start APScheduler
    - Log configuration summary

    Shutdown:
    - Stop scheduler
    - Dispose database connection pool
    """
    logger.info(
        "app_starting",
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )

    # ── Startup ───────────────────────────────────────────────────────────────
    try:
        # Verify database connection
        from app.database.connection import check_database_connection, create_all_tables
        db_ok = await check_database_connection()
        if db_ok:
            logger.info("database_connection_ok")
            if settings.is_development or settings.is_testing:
                await create_all_tables()
        else:
            logger.error("database_connection_failed")

        # SCHEDULER DISABLED — run tests/test_news_fetch.py first to verify fetchers work
        # from app.scheduler.scheduler import setup_scheduler
        # scheduler = setup_scheduler()
        # scheduler.start()
        # logger.info("scheduler_started", jobs=len(scheduler.get_jobs()))
        logger.info("scheduler_disabled", reason="manual_testing_mode")

    except Exception as exc:
        logger.error("startup_error", error=str(exc), exc_info=True)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("app_shutting_down")

    try:
        # SCHEDULER DISABLED — no scheduler to shut down
        # from app.scheduler.scheduler import get_scheduler
        # scheduler = get_scheduler()
        # if scheduler.running:
        #     scheduler.shutdown(wait=False)
        #     logger.info("scheduler_stopped")
        pass
    except Exception as exc:
        logger.warning("scheduler_shutdown_error", error=str(exc))

    try:
        from app.database.connection import dispose_engine
        await dispose_engine()
    except Exception as exc:
        logger.warning("engine_dispose_error", error=str(exc))

    logger.info("app_shutdown_complete")


# ── Application Factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """
    app = FastAPI(
        title="AI Pulse API",
        description=(
            "## AI Pulse – Personalized AI News Intelligence Platform\n\n"
            "A production-ready backend that automatically collects, verifies, "
            "deduplicates, and AI-analyzes the latest AI news — "
            "delivering a personalized daily brief to each user.\n\n"
            "### Features\n"
            "- 🤖 **Gemini AI** analysis with summaries, categories, and importance scores\n"
            "- 🔍 **5-layer duplicate detection** with semantic embeddings\n"
            "- ✅ **Trust scoring** with cross-source verification\n"
            "- 🎯 **Personalized daily briefs** based on user preferences\n"
            "- 🔔 **Firebase push notifications** via FCM\n"
            "- ⚡ **Upstash Redis** caching layer\n"
        ),
        version=settings.app_version,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Register Middleware ────────────────────────────────────────────────────
    from app.middleware import register_middleware
    register_middleware(app)

    # ── Register Routers ───────────────────────────────────────────────────────
    _register_routers(app)

    # ── Prometheus Metrics ────────────────────────────────────────────────────
    if settings.is_production:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator
            Instrumentator().instrument(app).expose(app)
        except ImportError:
            logger.warning("prometheus_not_available")

    logger.info("app_created", routers_count=len(app.routes))
    return app


def _register_routers(app: FastAPI) -> None:
    """Register all API routers."""
    from app.api.v1.auth import router as auth_router
    from app.api.v1.news import router as news_router
    from app.api.v1.routers import (
        admin_router,
        bookmarks_router,
        brief_router,
        categories_router,
        health_router,
        notifications_router,
        preferences_router,
        users_router,
    )

    prefix = settings.api_prefix

    # Health (no prefix — accessible at root)
    app.include_router(health_router)

    # Versioned API routes
    app.include_router(auth_router, prefix=prefix)
    app.include_router(users_router, prefix=prefix)
    app.include_router(preferences_router, prefix=prefix)
    app.include_router(news_router, prefix=prefix)
    app.include_router(brief_router, prefix=prefix)
    app.include_router(bookmarks_router, prefix=prefix)
    app.include_router(categories_router, prefix=prefix)
    app.include_router(notifications_router, prefix=prefix)
    app.include_router(admin_router, prefix=prefix)

    # Root UI Route
    from fastapi.responses import HTMLResponse
    import os

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_index():
        path = os.path.join("app", "templates", "index.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>AI Pulse UI Template Not Found</h1>")


# ── Application Instance ──────────────────────────────────────────────────────

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
        workers=1,
    )
