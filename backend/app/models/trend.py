"""
AI News Intelligence Engine – Trend Model
==========================================
Tracks trending topics, companies, keywords, models, and repositories
over rolling time windows. Populated by the Trending Engine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class Trend(BaseModel):
    """
    Represents a trending signal for a specific entity over a time window.

    Each row captures the trending state of one entity (company, keyword,
    model, etc.) for a specific time period. The Trending Engine creates
    new Trend rows every 6 hours.
    """

    __tablename__ = "trends"

    # ── Identification ─────────────────────────────────────────────────────────
    trend_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment=(
            "company | topic | keyword | repository | model | "
            "framework | startup | technology"
        ),
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name (e.g., 'OpenAI', 'RAG', 'llama.cpp')",
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="URL-safe lowercase slug",
    )

    # ── Time Window ────────────────────────────────────────────────────────────
    period_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=24,
        comment="Time window in hours (6, 24, 168 for 6h/1d/7d)",
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Start of the measurement window",
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="End of the measurement window",
    )

    # ── Trend Signals ──────────────────────────────────────────────────────────
    mention_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of times mentioned in the period",
    )
    source_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of distinct sources mentioning this",
    )
    event_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of news events featuring this trend",
    )
    previous_mention_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Mention count in the prior equivalent window (for velocity)",
    )

    # ── Scores ─────────────────────────────────────────────────────────────────
    trend_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        index=True,
        comment="Composite trending score 0-100 (velocity-weighted)",
    )
    velocity: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Growth rate vs. prior window (positive = trending up)",
    )
    is_emerging: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True if this topic appeared recently (< 48h) and is rising fast",
    )

    # ── Related Content ────────────────────────────────────────────────────────
    related_event_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="UUIDs of top events featuring this trend",
    )
    top_headline: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Headline of the most important event in this trend",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Brief description of why this is trending",
    )

    # ── Extra ──────────────────────────────────────────────────────────────────
    extra_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Flexible metadata (e.g., GitHub stars, Reddit score)",
    )

    # ── Constraints & Indexes ─────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "trend_type", "slug", "period_hours", "period_start",
            name="uq_trend_type_slug_period",
        ),
        Index("ix_trends_score_period", "trend_score", "period_end"),
        Index("ix_trends_type_score", "trend_type", "trend_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<Trend type={self.trend_type} name='{self.name}' "
            f"score={self.trend_score:.1f} period={self.period_hours}h>"
        )
