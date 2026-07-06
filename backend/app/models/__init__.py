"""
AI News Intelligence Engine – Category, Bookmark, DailyBrief, Notification,
NewsEvent, and Trend Models
====================================================================
All domain models for the application.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.news_article import NewsArticle


# ── Category ─────────────────────────────────────────────────────────────────

class Category(BaseModel):
    """AI news category (LLMs, AI Agents, Research, etc.)."""

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Emoji icon for the category",
    )
    color: Mapped[str | None] = mapped_column(
        String(7),
        nullable=True,
        comment="Hex color code (e.g., #6366f1)",
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        nullable=False,
        comment="Ordering for display purposes",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ── Bookmark ──────────────────────────────────────────────────────────────────

class Bookmark(BaseModel):
    """User-saved article bookmark."""

    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_bookmark_user_article"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news_articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional user note on the bookmark",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bookmarks")
    article: Mapped["NewsArticle"] = relationship(
        "NewsArticle", back_populates="bookmarks"
    )


# ── Daily Brief ───────────────────────────────────────────────────────────────

class DailyBrief(BaseModel):
    """
    Personalized daily news brief for a user.

    Generated once per day per user, containing a ranked, personalized
    selection of verified AI news articles.
    """

    __tablename__ = "daily_briefs"
    __table_args__ = (
        UniqueConstraint("user_id", "brief_date", name="uq_brief_user_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brief_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date this brief covers (UTC)",
    )

    # Ordered list of article IDs for this brief
    article_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
        comment="Ordered article UUIDs in the personalized brief",
    )

    # Metadata
    total_articles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    personalization_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="Average personalization relevance score",
    )

    # Delivery status
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    notification_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="daily_briefs")


# ── Notification ──────────────────────────────────────────────────────────────

class Notification(BaseModel):
    """
    FCM push notification record.

    Every notification sent to a user is persisted here
    for history, analytics, and unread count tracking.
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Content
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="daily_brief",
        index=True,
        comment="daily_brief | breaking_news | system",
    )
    data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional JSON payload for deep linking",
    )

    # Delivery
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    fcm_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Firebase message ID from FCM response",
    )
    delivery_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | sent | failed",
    )

    # User interaction
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="notifications")


# ── Register all models with SQLAlchemy ──────────────────────────────────
from app.models.user import User, UserPreferences
from app.models.news_event import NewsEvent
from app.models.news_article import NewsArticle
from app.models.news_source import NewsSource
from app.models.news_analysis import NewsAnalysis
from app.models.trend import Trend
