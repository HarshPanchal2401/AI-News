"""
AI News Intelligence Engine – NewsEvent Model
===============================================
Core event model. Multiple articles covering the same story are clustered
into a single NewsEvent. This is the primary entity surfaced to users.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel

if TYPE_CHECKING:
    from app.models.news_article import NewsArticle


class NewsEvent(BaseModel):
    """
    An AI news event — one per unique story, regardless of how many
    sources cover it.

    When multiple articles cover the same story (e.g. OpenAI releases GPT-5),
    they are all linked to the same NewsEvent. The Event is the canonical
    representation shown to users; Articles are supporting sources.
    """

    __tablename__ = "news_events"

    # ── Headline & Content ─────────────────────────────────────────────────────
    headline: Mapped[str] = mapped_column(
        String(600),
        nullable=False,
        comment="Best headline across all sources",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="2-4 sentence AI-generated event summary",
    )
    executive_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Longer executive summary (5-8 sentences)",
    )
    key_takeaways: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        nullable=False,
        server_default="{}",
        comment="3-5 key takeaways from the event",
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Classification ─────────────────────────────────────────────────────────
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="General AI",
        index=True,
        comment="Primary category: LLMs, AI Agents, Research, etc.",
    )
    subcategory: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Subcategory within the primary category",
    )
    event_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment=(
            "product_launch | model_release | funding | acquisition | "
            "research_paper | open_source_release | benchmark | "
            "security_incident | government_regulation | startup_launch | "
            "developer_tool | framework | api_release | infrastructure | "
            "gpu | robotics | ai_agent | coding_ai | healthcare_ai | "
            "education_ai | finance_ai"
        ),
    )

    # ── Priority Scores ────────────────────────────────────────────────────────
    priority_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        index=True,
        comment="Composite priority score 0-100 (95+=Breaking, 80+=Very Important)",
    )
    freshness_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Freshness score 0-100 (decays over time)",
    )
    trust_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Aggregate trust score from all covering sources",
    )
    trend_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Trending velocity score 0-100",
    )
    impact_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Industry impact score 0-100",
    )

    # ── Entities ───────────────────────────────────────────────────────────────
    companies: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="Companies/organizations mentioned",
    )
    products_mentioned: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    people_mentioned: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    technologies_mentioned: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    models_mentioned: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="AI models mentioned (GPT-4, Claude 3, Gemini, etc.)",
    )
    programming_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )

    # ── Funding & Research ─────────────────────────────────────────────────────
    funding_amount: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Funding amount in USD (millions)",
    )
    funding_currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Currency code (USD, EUR, etc.)",
    )
    research_paper_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    # ── Geographic & Industry ──────────────────────────────────────────────────
    countries_affected: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    industries_affected: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )

    # ── Market Analysis ────────────────────────────────────────────────────────
    market_impact: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="AI-assessed market impact description",
    )
    business_opportunities: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Sentiment & Signals ────────────────────────────────────────────────────
    sentiment: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="neutral",
        comment="positive | negative | neutral",
    )
    urgency: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        comment="breaking | high | medium | low",
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=70.0,
        nullable=False,
        comment="Confidence in the analysis 0-100",
    )

    # ── Breaking News ──────────────────────────────────────────────────────────
    is_breaking: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="True if priority >= 80 AND age < 4 hours",
    )
    notification_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether a breaking news notification was dispatched",
    )
    notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Source Aggregation ─────────────────────────────────────────────────────
    source_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="Number of sources covering this event",
    )
    source_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="List of domains covering this event",
    )
    primary_source_domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Most authoritative source domain",
    )
    primary_source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="URL of the primary/canonical article",
    )

    # ── Timeline ───────────────────────────────────────────────────────────────
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Earliest publication time across all sources",
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When we first detected this event",
    )
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the last new source was added",
    )

    # ── Embedding (for semantic search) ───────────────────────────────────────
    embedding_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Gemini text-embedding-004 vector for semantic search",
    )

    # ── Extra Metadata ─────────────────────────────────────────────────────────
    extra_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Flexible JSON for additional metadata",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    articles: Mapped[list["NewsArticle"]] = relationship(
        "NewsArticle",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    # ── Indexes ────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_news_events_priority_published", "priority_score", "published_at"),
        Index("ix_news_events_event_type_priority", "event_type", "priority_score"),
        Index("ix_news_events_category_priority", "category", "priority_score"),
        Index("ix_news_events_is_breaking_published", "is_breaking", "published_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<NewsEvent id={self.id} priority={self.priority_score:.1f} "
            f"headline='{self.headline[:50]}'>"
        )
