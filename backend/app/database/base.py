"""
AI Pulse – SQLAlchemy Declarative Base
========================================
Shared base class with automatic UUID primary keys,
created_at / updated_at timestamps, and a dict serializer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    # Allow Pydantic / JSON serialization helpers to see column info
    __abstract__ = True


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at columns to any model.
    Both columns are timezone-aware and managed by the database.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    """
    Mixin that adds a UUID primary key column.
    The UUID is generated client-side to allow references before DB insertion.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class BaseModel(UUIDMixin, TimestampMixin, Base):
    """
    Fully-featured base model combining UUID PK + timestamps.
    All domain models should inherit from this class.
    """

    __abstract__ = True

    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to a plain dictionary."""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, uuid.UUID):
                value = str(value)
            elif isinstance(value, datetime):
                value = value.isoformat()
            result[column.name] = value
        return result

    def __repr__(self) -> str:
        pk = getattr(self, "id", "?")
        return f"<{self.__class__.__name__} id={pk}>"
