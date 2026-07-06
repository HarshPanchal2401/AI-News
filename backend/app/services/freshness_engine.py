"""
AI News Intelligence Engine – Freshness Engine
================================================
Tracks and computes freshness signals for NewsEvents.

Freshness Score Decay:
  0h  → 100  (just published)
  2h  → 95
  6h  → 80
  12h → 60
  24h → 40
  48h → 20
  72h → 10
  7d+ → 2

Breaking News: priority >= 80 AND age < 4 hours
Rejection threshold: articles > 7 days old AND priority < 60
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.services.news_fetchers.base import RawArticle

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
BREAKING_MAX_AGE_HOURS = 4.0          # Must be < 4h old to be "breaking"
BREAKING_MIN_PRIORITY = 80.0          # Must have priority >= 80 for breaking
REJECTION_MAX_AGE_HOURS = 168.0       # 7 days
REJECTION_MIN_PRIORITY = 60.0         # Override rejection for high-priority news


@dataclass
class FreshnessResult:
    """Freshness analysis for an article or event."""
    freshness_score: float       # 0–100
    age_hours: float             # Age in hours
    is_breaking: bool            # True if < 4h old AND priority >= 80
    is_stale: bool               # True if > 7 days old AND priority < 60
    should_reject: bool          # True if stale and not important enough
    urgency: str                 # breaking | high | medium | low


def compute_freshness_score(published_at: datetime | None) -> float:
    """
    Compute freshness score using smooth exponential-like decay.
    Returns value between 2.0 and 100.0.
    """
    if published_at is None:
        return 30.0

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)

    # Piecewise linear decay
    if age_hours < 2:
        score = 100.0
    elif age_hours < 6:
        score = 100.0 - (age_hours - 2) * 3.75
    elif age_hours < 12:
        score = 85.0 - (age_hours - 6) * 4.17
    elif age_hours < 24:
        score = 60.0 - (age_hours - 12) * 1.67
    elif age_hours < 48:
        score = 40.0 - (age_hours - 24) * 0.83
    elif age_hours < 168:
        score = 20.0 - (age_hours - 48) * 0.107
    else:
        score = 2.0

    return round(max(2.0, min(100.0, score)), 2)


def compute_age_hours(published_at: datetime | None) -> float:
    """Return article age in hours."""
    if published_at is None:
        return 0.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 3600)


def analyze_freshness(
    published_at: datetime | None,
    priority_score: float = 0.0,
) -> FreshnessResult:
    """
    Full freshness analysis for a news item.

    Args:
        published_at: Publication timestamp.
        priority_score: Current priority score (affects rejection logic).

    Returns:
        FreshnessResult with all freshness signals.
    """
    age_hours = compute_age_hours(published_at)
    freshness_score = compute_freshness_score(published_at)

    # Breaking: very recent + high priority
    is_breaking = (
        age_hours <= BREAKING_MAX_AGE_HOURS
        and priority_score >= BREAKING_MIN_PRIORITY
    )

    # Stale: older than 7 days
    is_stale = age_hours > REJECTION_MAX_AGE_HOURS

    # Reject if stale AND not important enough to resurface
    should_reject = is_stale and priority_score < REJECTION_MIN_PRIORITY

    # Urgency label
    if is_breaking:
        urgency = "breaking"
    elif age_hours <= 6:
        urgency = "high"
    elif age_hours <= 24:
        urgency = "medium"
    else:
        urgency = "low"

    return FreshnessResult(
        freshness_score=freshness_score,
        age_hours=round(age_hours, 2),
        is_breaking=is_breaking,
        is_stale=is_stale,
        should_reject=should_reject,
        urgency=urgency,
    )


def should_accept_article(article: RawArticle) -> tuple[bool, str]:
    """
    Determine whether a raw article should be accepted based on freshness.

    Returns:
        (should_accept, reason)
    """
    if article.published_at is None:
        # No date — accept with caution (assume recent)
        return True, "no_date_assumed_recent"

    age_hours = compute_age_hours(article.published_at)

    # Reject future-dated articles (with 15-minute tolerance for clock skew)
    if age_hours < -0.25:
        return False, f"future_dated_{age_hours:.1f}h_ahead"

    # Reject very old articles
    if age_hours > REJECTION_MAX_AGE_HOURS:
        return False, f"too_old_{age_hours:.0f}h"

    return True, "accepted"


class FreshnessEngine:
    """
    Updates freshness scores for NewsEvents in the database.
    Called periodically by the scheduler to keep scores current.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def refresh_all_events(self) -> int:
        """
        Recompute freshness scores for all recent events.
        Called every 2 hours by the scheduler.

        Returns:
            Number of events updated.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=168)  # 7 days

        stmt = (
            select(NewsEvent)
            .where(NewsEvent.published_at >= cutoff)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()

        updated = 0
        for event in events:
            new_freshness = compute_freshness_score(event.published_at)
            if abs(new_freshness - event.freshness_score) > 0.5:
                event.freshness_score = new_freshness

                # Update breaking status
                freshness_result = analyze_freshness(
                    event.published_at,
                    priority_score=event.priority_score,
                )
                event.is_breaking = freshness_result.is_breaking
                updated += 1

        if updated > 0:
            try:
                await self.db.commit()
            except Exception as exc:
                logger.error("freshness_refresh_error", error=str(exc))
                await self.db.rollback()
                return 0

        logger.info("freshness_refresh_complete", events_updated=updated)
        return updated

    async def mark_events_not_breaking(self, max_age_hours: float = 4.0) -> int:
        """
        Clear breaking status for events older than max_age_hours.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.is_breaking == True,  # noqa: E712
                NewsEvent.published_at < cutoff,
            )
        )
        result = await self.db.execute(stmt)
        stale_breaking = result.scalars().all()

        for event in stale_breaking:
            event.is_breaking = False

        if stale_breaking:
            await self.db.commit()

        logger.info("breaking_status_cleared", count=len(stale_breaking))
        return len(stale_breaking)
