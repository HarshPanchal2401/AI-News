"""
AI Pulse – Date/Time Utilities
================================
Timezone-aware datetime helpers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def today_utc() -> date:
    """Return today's date in UTC."""
    return utcnow().date()


def hours_ago(hours: int) -> datetime:
    """Return a datetime N hours before now (UTC)."""
    return utcnow() - timedelta(hours=hours)


def days_ago(days: int) -> datetime:
    """Return a datetime N days before now (UTC)."""
    return utcnow() - timedelta(days=days)


def hours_since(dt: datetime) -> float:
    """
    Return the number of hours elapsed since a given datetime.

    Args:
        dt: A timezone-aware or naive datetime. Naive datetimes are
            assumed to be UTC.

    Returns:
        Hours elapsed as a float.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = utcnow() - dt
    return delta.total_seconds() / 3600


def freshness_score(published_at: datetime, half_life_hours: float = 24.0) -> float:
    """
    Compute an exponential decay freshness score (0.0–1.0).

    score = e^(-hours_old / half_life_hours)

    A brand-new article scores 1.0; after `half_life_hours` it scores ~0.37.

    Args:
        published_at: When the article was published.
        half_life_hours: Hours until score decays to ~37%.

    Returns:
        Freshness score between 0.0 and 1.0.
    """
    import math

    age_hours = max(0.0, hours_since(published_at))
    return math.exp(-age_hours / half_life_hours)


def parse_datetime(value: str | None) -> datetime | None:
    """
    Parse a datetime string into a timezone-aware datetime.
    Handles ISO 8601 and RFC 2822 formats.

    Returns None if parsing fails.
    """
    if not value:
        return None
    from dateutil import parser as dateutil_parser  # type: ignore

    try:
        dt = dateutil_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 string with UTC offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def start_of_day(dt: datetime | None = None) -> datetime:
    """Return midnight UTC for the given date (or today)."""
    target = dt or utcnow()
    return target.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def end_of_day(dt: datetime | None = None) -> datetime:
    """Return end-of-day UTC for the given date (or today)."""
    target = dt or utcnow()
    return target.replace(
        hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
    )
