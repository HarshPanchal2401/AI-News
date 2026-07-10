"""
AI News Intelligence Engine – FastAPI Application Entry Point
==============================================================
Production-ready backend that continuously discovers, validates,
processes, prioritizes, clusters, and surfaces AI news.
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

        # Start the Intelligence Engine scheduler
        from app.scheduler.scheduler import setup_scheduler
        scheduler = setup_scheduler()
        scheduler.start()
        logger.info(
            "scheduler_started",
            jobs=len(scheduler.get_jobs()),
            fetch_interval_hours=2,
        )

    except Exception as exc:
        logger.error("startup_error", error=str(exc), exc_info=True)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("app_shutting_down")

    try:
        from app.scheduler.scheduler import get_scheduler
        scheduler = get_scheduler()
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("scheduler_stopped")
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
        title="AI News Intelligence Engine API",
        description=(
            "## AI News Intelligence Engine\n\n"
            "A production-ready backend that continuously discovers, validates, "
            "processes, clusters, prioritizes, and surfaces the latest AI news from ~30 sources.\n\n"
            "### Features\n"
            "- 🤖 **Gemini AI** 25-field analysis (summaries, entities, market impact, predictions)\n"
            "- 🔍 **5-layer duplicate detection** + event clustering (same-story grouping)\n"
            "- 📊 **Priority Engine** (0-100 score: freshness, trust, source count, impact)\n"
            "- 📈 **Trending Engine** (companies, topics, models, keywords over 6h/24h/7d)\n"
            "- 📰 **Daily Digest** (top news, funding, research, product launches, predictions)\n"
            "- 🔔 **Breaking News Notifications** via Firebase FCM\n"
            "- 🔎 **Semantic Search** using Gemini embeddings\n"
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

    # Intelligence Engine routes (✨ NEW)
    from app.api.v1.intelligence import router as intelligence_router
    app.include_router(intelligence_router, prefix=prefix)

    # Root UI Route
    from fastapi.responses import HTMLResponse, FileResponse
    import os

    def find_frontend_file(filename: str) -> str | None:
        """Find frontend file using multiple fallback locations."""
        paths_to_try = [
            os.path.join("frontend", filename),             # Running from repo root (Docker/Prod)
            os.path.join("..", "frontend", filename),        # Running from backend/ (Local dev)
            os.path.join("app", "templates", filename),     # Legacy fallback
        ]
        for path in paths_to_try:
            if os.path.exists(path):
                return path
        return None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_index():
        path = find_frontend_file("index.html")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>AI News Frontend Not Found</h1>")

    @app.get("/logo.png", include_in_schema=False)
    async def serve_logo():
        path = find_frontend_file("logo.png")
        if path:
            return FileResponse(path)
        return HTMLResponse(content="", status_code=404)

    @app.get("/logo_light.png", include_in_schema=False)
    async def serve_logo_light():
        path = find_frontend_file("logo_light.png")
        if not path:
            path = find_frontend_file("logo.png")
        if path:
            return FileResponse(path)
        return HTMLResponse(content="", status_code=404)



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
