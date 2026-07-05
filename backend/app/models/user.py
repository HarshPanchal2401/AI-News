"""
AI Pulse – User Model
======================
Represents an authenticated user linked to Supabase Auth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel

if TYPE_CHECKING:
    from app.models import Bookmark, DailyBrief, Notification


class User(BaseModel):
    """
    Application user.

    Linked 1:1 to a Supabase Auth account via `supabase_id`.
    Stores profile information and preferences reference.
    """

    __tablename__ = "users"

    # ── Identity ───────────────────────────────────────────────────────────────
    supabase_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Supabase Auth user UUID",
    )
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    hashed_password: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ── Activity ───────────────────────────────────────────────────────────────
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── FCM Token ──────────────────────────────────────────────────────────────
    fcm_token: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Firebase Cloud Messaging device token",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    preferences: Mapped["UserPreferences | None"] = relationship(
        "UserPreferences",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    bookmarks: Mapped[list["Bookmark"]] = relationship(
        "Bookmark",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_briefs: Mapped[list["DailyBrief"]] = relationship(
        "DailyBrief",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserPreferences(BaseModel):
    """
    User personalization preferences.

    Stores arrays of favored companies, categories, topics,
    and notification settings.
    """

    __tablename__ = "user_preferences"

    # ── Foreign Key ────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        __import__("sqlalchemy").ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # ── Content Preferences ────────────────────────────────────────────────────
    favorite_companies: Mapped[list[str]] = mapped_column(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["ARRAY"]).ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    favorite_categories: Mapped[list[str]] = mapped_column(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["ARRAY"]).ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    favorite_topics: Mapped[list[str]] = mapped_column(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["ARRAY"]).ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    blocked_topics: Mapped[list[str]] = mapped_column(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["ARRAY"]).ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )
    bookmarked_articles: Mapped[list[str]] = mapped_column(
        __import__("sqlalchemy.dialects.postgresql", fromlist=["ARRAY"]).ARRAY(String),
        default=list,
        nullable=False,
        server_default="{}",
    )

    # ── Notification Preferences ───────────────────────────────────────────────
    notification_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    notification_hour: Mapped[int] = mapped_column(
        __import__("sqlalchemy").SmallInteger,
        default=10,
        nullable=False,
        comment="Hour (UTC 0-23) to receive daily notification",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="preferences",
    )
