"""
AI Pulse – Test Configuration & Fixtures
==========================================
Shared pytest fixtures for the entire test suite.
Uses an in-memory SQLite (for tests) or test Supabase schema.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.base import Base
from app.models.news_article import NewsArticle
from app.models.news_analysis import NewsAnalysis
from app.models.news_source import NewsSource
from app.models.user import User, UserPreferences
from app.services.news_fetchers.base import RawArticle

# Override settings for testing
import os
os.environ.setdefault("APP_ENV", "testing")




# ── Test Database ─────────────────────────────────────────────────────────────

@pytest.fixture
async def test_engine():
    """Create a test SQLAlchemy engine (uses SQLite for speed)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session that rolls back after each test."""
    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ── Test Client ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX test client for the FastAPI app."""
    from app.main import app
    from app.database.connection import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Sample Data Factories ──────────────────────────────────────────────────────

@pytest.fixture
def sample_raw_article() -> RawArticle:
    """Create a sample RawArticle for testing."""
    return RawArticle(
        title="OpenAI Launches GPT-6 with Unprecedented Capabilities",
        url="https://openai.com/blog/gpt-6-launch",
        source_name="openai_blog",
        source_domain="openai.com",
        description="OpenAI today announced GPT-6, its most capable model yet.",
        published_at=datetime.now(timezone.utc),
        is_official=True,
        official_company="OpenAI",
    )


@pytest.fixture
def sample_raw_article_duplicate(sample_raw_article) -> RawArticle:
    """A duplicate of the sample article from a different source."""
    return RawArticle(
        title="OpenAI Unveils GPT-6, Its Most Advanced AI Model",
        url="https://techcrunch.com/2024/01/15/openai-gpt-6",
        source_name="techcrunch_ai",
        source_domain="techcrunch.com",
        description="OpenAI has officially unveiled GPT-6.",
        published_at=datetime.now(timezone.utc),
        is_official=False,
    )


@pytest.fixture
async def sample_user(db: AsyncSession) -> User:
    """Create a test user in the database."""
    user = User(
        supabase_id=str(uuid.uuid4()),
        email="test@aipulse.dev",
        display_name="Test User",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    prefs = UserPreferences(
        user_id=user.id,
        favorite_companies=["OpenAI", "Google"],
        favorite_categories=["LLMs", "Research"],
        notification_enabled=True,
    )
    db.add(prefs)
    await db.commit()
    return user


@pytest.fixture
async def sample_article(db: AsyncSession) -> NewsArticle:
    """Create a test verified article with analysis."""
    article = NewsArticle(
        title="OpenAI Launches GPT-6 with Unprecedented Capabilities",
        normalized_title="openai launches gpt 6 with unprecedented capabilities",
        url="https://openai.com/blog/gpt-6-launch",
        normalized_url="https://openai.com/blog/gpt-6-launch",
        source_domain="openai.com",
        title_fingerprint="abc123",
        content_fingerprint="def456",
        is_verified=True,
        trust_score=95.0,
        ai_processed=True,
        importance_score=90.0,
        final_score=85.0,
        is_official_source=True,
        published_at=datetime.now(timezone.utc),
    )
    db.add(article)
    await db.flush()

    analysis = NewsAnalysis(
        article_id=article.id,
        summary="OpenAI announced GPT-6, their most advanced language model.",
        category="LLMs",
        companies=["OpenAI"],
        keywords=["GPT-6", "language model", "AI"],
        tags=["breakthrough", "product-launch"],
        importance_score=90.0,
        why_it_matters="GPT-6 represents a major leap in AI capabilities.",
        reading_time_minutes=4,
    )
    db.add(analysis)
    await db.commit()
    return article


@pytest.fixture
def mock_gemini_client():
    """Mock the Gemini client to avoid real API calls in tests."""
    with patch("app.services.ai.gemini_client.get_gemini_client") as mock:
        client = MagicMock()
        client.generate_json = AsyncMock(return_value={
            "summary": "Test AI-generated summary.",
            "category": "LLMs",
            "companies": ["OpenAI"],
            "keywords": ["GPT", "language model"],
            "importance_score": 75,
            "why_it_matters": "This matters because it advances AI capabilities.",
            "reading_time_minutes": 3,
            "tags": ["breakthrough"],
        })
        client.generate_embedding = AsyncMock(return_value=[0.1] * 768)
        mock.return_value = client
        yield client


@pytest.fixture
def mock_redis():
    """Mock Redis client to avoid real Upstash calls in tests."""
    with patch("app.services.cache.redis_client.get_redis_client") as mock:
        client = MagicMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock(return_value=True)
        client.delete = AsyncMock(return_value=1)
        client.ping = AsyncMock(return_value=True)
        client.incr = AsyncMock(return_value=1)
        client.expire = AsyncMock(return_value=True)
        client.ttl = AsyncMock(return_value=60)
        mock.return_value = client
        yield client
