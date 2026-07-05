"""
AI Pulse – Database Connection
================================
Async SQLAlchemy engine and session factory for Supabase PostgreSQL.
Provides FastAPI dependency for injecting database sessions.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Engine Configuration ───────────────────────────────────────────────────────

def _build_engine() -> AsyncEngine:
    """
    Create the async SQLAlchemy engine.

    Uses NullPool for serverless/cloud environments (Render, Supabase)
    to avoid connection pool exhaustion.
    """
    engine_kwargs: dict[str, Any] = {
        "echo": settings.is_development,
        "future": True,
    }

    if settings.is_production:
        # Production: connection pooling disabled (handled by Supabase's PgBouncer)
        engine_kwargs["poolclass"] = NullPool
    else:
        # Development: small pool
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10
        engine_kwargs["pool_pre_ping"] = True

    return create_async_engine(settings.database_url, **engine_kwargs)


# Singleton engine instance
engine: AsyncEngine = _build_engine()

# Session factory
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── FastAPI Dependency ─────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage:
        @router.get("/example")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Database Health Check ─────────────────────────────────────────────────────

async def check_database_connection() -> bool:
    """
    Verify the database connection is alive.

    Returns:
        True if connected, False otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("database_connection_failed", error=str(exc))
        return False


# ── Table Creation ─────────────────────────────────────────────────────────────

async def create_all_tables() -> None:
    """
    Create all tables defined in SQLAlchemy models.
    Should only be used in development — use Alembic migrations in production.
    """
    from app.database.base import Base

    # Import all models so Base knows about them
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created")


async def dispose_engine() -> None:
    """Dispose of the engine connection pool. Call on application shutdown."""
    await engine.dispose()
    logger.info("database_engine_disposed")
