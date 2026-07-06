"""
AI News Intelligence Engine – News Analysis Model
===================================================
Stores Gemini-generated analysis for each article (1:1 with NewsArticle).
Extended with full 25-field AI enrichment for the Intelligence Engine.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class NewsAnalysis(BaseModel):
    """
    AI-generated analysis for a news article.

    Created by Gemini and stored in a separate table to keep the core
    article table lean. Extended with the full Intelligence Engine
    enrichment schema (25+ fields).
    """

    __tablename__ = "news_analyses"

    # ── Foreign Key ────────────────────────────────────────────────────────────
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news_articles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # ── Core Summary ───────────────────────────────────────────────────────────
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="2-4 sentence AI-generated summary",
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
        comment="3-5 key takeaways from the article",
    )
    why_it_matters: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="1-2 sentences on real-world impact",
    )

    # ── Classification ─────────────────────────────────────────────────────────
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Primary category: LLMs, AI Agents, Research, etc.",
    )
    subcategory: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Subcategory e.g. 'Reasoning Models', 'Image Generation'",
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
        comment="Funding amount in USD millions, if applicable",
    )
    funding_currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
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

    # ── Market Intelligence ────────────────────────────────────────────────────
    market_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_opportunities: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Sentiment & Urgency ────────────────────────────────────────────────────
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
        nullable=False,
        default=70.0,
        comment="Confidence in analysis accuracy 0-100",
    )

    # ── Scores ─────────────────────────────────────────────────────────────────
    importance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="AI-assigned importance 0-100",
    )
    priority_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Priority Engine score 0-100",
    )

    # ── Reading ────────────────────────────────────────────────────────────────
    reading_time_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="Estimated reading time in minutes",
    )

    # ── Gemini Model Metadata ──────────────────────────────────────────────────
    model_used: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="gemini-2.0-flash",
        comment="Gemini model version that generated this analysis",
    )
    prompt_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="v2",
        comment="Analysis prompt version for tracking improvements",
    )

    # ── Relationship ───────────────────────────────────────────────────────────
    article: Mapped["NewsArticle"] = relationship(  # type: ignore[name-defined]
        "NewsArticle",
        back_populates="analysis",
    )
