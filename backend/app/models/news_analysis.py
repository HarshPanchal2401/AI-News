"""
AI Pulse – News Analysis Model
================================
Stores Gemini-generated analysis for each article (1:1 with NewsArticle).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class NewsAnalysis(BaseModel):
    """
    AI-generated analysis for a news article.

    Created by Gemini 2.5 Flash and stored in a separate table
    to keep the core article table lean.
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

    # ── Gemini Outputs ─────────────────────────────────────────────────────────
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="2-4 sentence AI-generated summary",
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Primary category: LLMs, AI Agents, Research, etc.",
    )
    companies: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="Companies mentioned (normalized names)",
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="Key terms extracted from the article",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
        comment="Descriptive tags: breakthrough, open-source, safety, etc.",
    )
    importance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="AI-assigned importance 0-100",
    )
    why_it_matters: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="1-2 sentences on why this news matters",
    )
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

    # ── Relationship ───────────────────────────────────────────────────────────
    article: Mapped["NewsArticle"] = relationship(  # type: ignore[name-defined]
        "NewsArticle",
        back_populates="analysis",
    )
