"""
AI Pulse – News Source Model
==============================
Represents a news source (RSS feed, API endpoint, or scrape target).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel

if TYPE_CHECKING:
    from app.models.news_article import NewsArticle

# Source type literals
SourceType = Literal["rss", "api", "scrape"]


class NewsSource(BaseModel):
    """
    Represents an external AI news source.

    Tracks source metadata, health, reliability score, and fetch history.
    """

    __tablename__ = "news_sources"

    # ── Identity ───────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="rss | api | scrape",
    )
    domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Root domain (e.g., 'techcrunch.com')",
    )

    # ── Trust & Reliability ────────────────────────────────────────────────────
    reliability_score: Mapped[float] = mapped_column(
        Float,
        default=70.0,
        nullable=False,
        comment="Source reliability score 0-100",
    )
    is_official: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True if this is an official company blog/newsroom",
    )
    official_company: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        comment="Company name if this is an official source",
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Consecutive fetch failures — disable source after threshold",
    )

    # ── Fetch History ──────────────────────────────────────────────────────────
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_successful_fetch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_articles_fetched: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    articles: Mapped[list["NewsArticle"]] = relationship(
        "NewsArticle",
        back_populates="source",
    )
