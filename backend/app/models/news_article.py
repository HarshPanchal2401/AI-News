"""
AI Pulse – News Article Model
===============================
Core article model with verification, deduplication, and ranking data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel

if TYPE_CHECKING:
    from app.models.news_analysis import NewsAnalysis
    from app.models.news_source import NewsSource
    from app.models import Bookmark


class NewsArticle(BaseModel):
    """
    Verified and processed AI news article.

    A canonical article may have multiple supporting sources
    (self-referencing relationship via canonical_id).
    """

    __tablename__ = "news_articles"

    # ── Content ────────────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    normalized_title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        comment="Lowercased, punctuation-stripped title for matching",
    )
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        index=True,
    )
    normalized_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="URL stripped of tracking params for deduplication",
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Short description or lede from the source",
    )
    content_snippet: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="First ~500 chars of article body",
    )
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # ── Source ─────────────────────────────────────────────────────────────────
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # ── Hashes (for duplicate detection) ──────────────────────────────────────
    title_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="SHA-256 of normalized title",
    )
    content_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="SHA-256 of normalized title + body snippet",
    )
    entity_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="SHA-256 of company + product + event triple",
    )

    # ── Embedding Vector (stored as text JSON for Supabase) ───────────────────
    embedding_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Gemini text-embedding-004 vector as JSON array string",
    )

    # ── Deduplication ─────────────────────────────────────────────────────────
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    canonical_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news_articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Points to the canonical article if this is a duplicate",
    )
    supporting_sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        nullable=False,
        server_default="{}",
        comment="URLs of other sources covering same story",
    )

    # ── Verification ──────────────────────────────────────────────────────────
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    trust_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        index=True,
        comment="Trust score 0-100",
    )
    verification_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── AI Processing ─────────────────────────────────────────────────────────
    ai_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    importance_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        index=True,
        comment="AI-generated importance score 0-100",
    )

    # ── Ranking ────────────────────────────────────────────────────────────────
    final_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        index=True,
        comment="Weighted final ranking score",
    )
    is_official_source: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ── Engagement Tracking ────────────────────────────────────────────────────
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bookmark_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    source: Mapped["NewsSource | None"] = relationship(
        "NewsSource",
        back_populates="articles",
        foreign_keys=[source_id],
    )
    analysis: Mapped["NewsAnalysis | None"] = relationship(
        "NewsAnalysis",
        back_populates="article",
        uselist=False,
        cascade="all, delete-orphan",
    )
    bookmarks: Mapped[list["Bookmark"]] = relationship(
        "Bookmark",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    duplicates: Mapped[list["NewsArticle"]] = relationship(
        "NewsArticle",
        foreign_keys=[canonical_id],
        back_populates="canonical_article",
    )
    canonical_article: Mapped["NewsArticle | None"] = relationship(
        "NewsArticle",
        remote_side="NewsArticle.id",
        foreign_keys=[canonical_id],
        back_populates="duplicates",
    )

    # ── Indexes ────────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_news_articles_published_at_verified", "published_at", "is_verified"),
        Index("ix_news_articles_final_score_verified", "final_score", "is_verified"),
        Index("ix_news_articles_is_duplicate_verified", "is_duplicate", "is_verified"),
    )
