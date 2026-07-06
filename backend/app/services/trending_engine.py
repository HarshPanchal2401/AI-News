"""
AI News Intelligence Engine – Trending Engine
===============================================
Analyzes recent NewsEvents to detect trending topics, companies,
models, keywords, and repositories over rolling time windows.

Tracks:
  - Most mentioned companies (24h, 7d)
  - Fastest growing topics (velocity)
  - Emerging keywords (new in last 6h)
  - Trending AI models
  - Trending frameworks & tools
  - Trending GitHub repositories
  - Trending research topics

Generates Trend records saved to the DB.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.models.trend import Trend

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
TREND_WINDOWS = [6, 24, 168]  # Hours: 6h, 1d, 7d


class TrendingEngine:
    """
    Analyzes recent events to identify trending signals.

    Usage:
        engine = TrendingEngine(db)
        await engine.compute_trends()
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def compute_trends(self) -> dict[str, int]:
        """
        Compute trends for all windows and save to DB.

        Returns:
            Stats: {trends_created, trends_updated}
        """
        stats = {"trends_created": 0, "trends_updated": 0}

        for window_hours in TREND_WINDOWS:
            window_stats = await self._compute_window(window_hours)
            stats["trends_created"] += window_stats.get("created", 0)
            stats["trends_updated"] += window_stats.get("updated", 0)

        try:
            await self.db.commit()
        except Exception as exc:
            logger.error("trending_commit_error", error=str(exc))
            await self.db.rollback()

        logger.info(
            "trending_complete",
            trends_created=stats["trends_created"],
            trends_updated=stats["trends_updated"],
        )
        return stats

    async def _compute_window(self, window_hours: int) -> dict[str, int]:
        """Compute all trend types for a single time window."""
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=window_hours)
        period_end = now

        # Also fetch prior window for velocity calculation
        prior_start = period_start - timedelta(hours=window_hours)

        # Fetch events in current window
        current_events = await self._fetch_events(period_start, period_end)
        prior_events = await self._fetch_events(prior_start, period_start)

        if not current_events:
            return {"created": 0, "updated": 0}

        # Analyze signals
        company_signals = self._analyze_companies(current_events, prior_events)
        topic_signals = self._analyze_topics(current_events, prior_events)
        model_signals = self._analyze_models(current_events, prior_events)
        keyword_signals = self._analyze_keywords(current_events, prior_events)
        tech_signals = self._analyze_technologies(current_events, prior_events)

        all_signals = (
            company_signals
            + topic_signals
            + model_signals
            + keyword_signals
            + tech_signals
        )

        # Save trends to DB
        created = updated = 0
        for signal in all_signals:
            was_created = await self._save_trend(
                signal, window_hours, period_start, period_end
            )
            if was_created:
                created += 1
            else:
                updated += 1

        return {"created": created, "updated": updated}

    async def _fetch_events(
        self, start: datetime, end: datetime
    ) -> list[NewsEvent]:
        """Fetch events within a time range."""
        stmt = (
            select(NewsEvent)
            .where(
                and_(
                    NewsEvent.published_at >= start,
                    NewsEvent.published_at < end,
                )
            )
            .order_by(NewsEvent.priority_score.desc())
            .limit(500)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ── Signal Analyzers ───────────────────────────────────────────────────────

    def _analyze_companies(
        self,
        current: list[NewsEvent],
        prior: list[NewsEvent],
    ) -> list[dict]:
        """Analyze company mentions."""
        current_counts: Counter[str] = Counter()
        event_map: dict[str, list[str]] = defaultdict(list)

        for event in current:
            for company in event.companies or []:
                if company and len(company) > 1:
                    current_counts[company] += 1
                    event_map[company].append(str(event.id))

        prior_counts: Counter[str] = Counter()
        for event in prior:
            for company in event.companies or []:
                if company:
                    prior_counts[company] += 1

        signals = []
        for company, count in current_counts.most_common(20):
            prior_count = prior_counts.get(company, 0)
            velocity = self._compute_velocity(count, prior_count)
            trend_score = self._compute_trend_score(count, velocity, len(current))

            # Get top headline
            top_event = max(
                (e for e in current if company in (e.companies or [])),
                key=lambda e: e.priority_score,
                default=None,
            )

            signals.append({
                "trend_type": "company",
                "name": company,
                "slug": self._slugify(company),
                "mention_count": count,
                "source_count": len({e.primary_source_domain for e in current
                                     if company in (e.companies or [])}),
                "event_count": len(event_map[company]),
                "previous_mention_count": prior_count,
                "trend_score": trend_score,
                "velocity": velocity,
                "is_emerging": prior_count == 0 and count >= 2,
                "related_event_ids": event_map[company][:5],
                "top_headline": top_event.headline[:200] if top_event else None,
            })

        return signals

    def _analyze_topics(
        self,
        current: list[NewsEvent],
        prior: list[NewsEvent],
    ) -> list[dict]:
        """Analyze topic trends from categories + event_types."""
        current_counts: Counter[str] = Counter()
        event_map: dict[str, list[str]] = defaultdict(list)

        for event in current:
            if event.event_type:
                label = event.event_type.replace("_", " ").title()
                current_counts[label] += 1
                event_map[label].append(str(event.id))

        prior_counts: Counter[str] = Counter()
        for event in prior:
            if event.event_type:
                label = event.event_type.replace("_", " ").title()
                prior_counts[label] += 1

        signals = []
        for topic, count in current_counts.most_common(15):
            prior_count = prior_counts.get(topic, 0)
            velocity = self._compute_velocity(count, prior_count)
            trend_score = self._compute_trend_score(count, velocity, len(current))

            top_event = max(
                (e for e in current
                 if e.event_type and e.event_type.replace("_", " ").title() == topic),
                key=lambda e: e.priority_score,
                default=None,
            )

            signals.append({
                "trend_type": "topic",
                "name": topic,
                "slug": self._slugify(topic),
                "mention_count": count,
                "source_count": 0,
                "event_count": len(event_map[topic]),
                "previous_mention_count": prior_count,
                "trend_score": trend_score,
                "velocity": velocity,
                "is_emerging": prior_count == 0 and count >= 2,
                "related_event_ids": event_map[topic][:5],
                "top_headline": top_event.headline[:200] if top_event else None,
            })

        return signals

    def _analyze_models(
        self,
        current: list[NewsEvent],
        prior: list[NewsEvent],
    ) -> list[dict]:
        """Analyze AI model mention trends."""
        current_counts: Counter[str] = Counter()
        event_map: dict[str, list[str]] = defaultdict(list)

        for event in current:
            for model in event.models_mentioned or []:
                if model and len(model) > 2:
                    current_counts[model] += 1
                    event_map[model].append(str(event.id))

        prior_counts: Counter[str] = Counter()
        for event in prior:
            for model in event.models_mentioned or []:
                if model:
                    prior_counts[model] += 1

        signals = []
        for model_name, count in current_counts.most_common(15):
            prior_count = prior_counts.get(model_name, 0)
            velocity = self._compute_velocity(count, prior_count)
            trend_score = self._compute_trend_score(count, velocity, len(current))

            top_event = max(
                (e for e in current if model_name in (e.models_mentioned or [])),
                key=lambda e: e.priority_score,
                default=None,
            )

            signals.append({
                "trend_type": "model",
                "name": model_name,
                "slug": self._slugify(model_name),
                "mention_count": count,
                "source_count": 0,
                "event_count": len(event_map[model_name]),
                "previous_mention_count": prior_count,
                "trend_score": trend_score,
                "velocity": velocity,
                "is_emerging": prior_count == 0 and count >= 2,
                "related_event_ids": event_map[model_name][:5],
                "top_headline": top_event.headline[:200] if top_event else None,
            })

        return signals

    def _analyze_keywords(
        self,
        current: list[NewsEvent],
        prior: list[NewsEvent],
    ) -> list[dict]:
        """Analyze emerging keyword trends."""
        current_counts: Counter[str] = Counter()
        event_map: dict[str, list[str]] = defaultdict(list)

        for event in current:
            for kw in event.keywords or []:
                if kw and len(kw) > 3:
                    current_counts[kw.lower()] += 1
                    event_map[kw.lower()].append(str(event.id))

        prior_counts: Counter[str] = Counter()
        for event in prior:
            for kw in event.keywords or []:
                if kw:
                    prior_counts[kw.lower()] += 1

        # Focus on keywords with high velocity (emerging ones)
        signals = []
        for keyword, count in current_counts.most_common(20):
            prior_count = prior_counts.get(keyword, 0)
            velocity = self._compute_velocity(count, prior_count)

            # Only include keywords with meaningful velocity or high counts
            if count < 2 and velocity < 50:
                continue

            trend_score = self._compute_trend_score(count, velocity, len(current))
            signals.append({
                "trend_type": "keyword",
                "name": keyword,
                "slug": self._slugify(keyword),
                "mention_count": count,
                "source_count": 0,
                "event_count": len(event_map[keyword]),
                "previous_mention_count": prior_count,
                "trend_score": trend_score,
                "velocity": velocity,
                "is_emerging": prior_count == 0 and count >= 2,
                "related_event_ids": event_map[keyword][:5],
                "top_headline": None,
            })

        return signals[:10]  # Top 10 keywords only

    def _analyze_technologies(
        self,
        current: list[NewsEvent],
        prior: list[NewsEvent],
    ) -> list[dict]:
        """Analyze technology mention trends."""
        current_counts: Counter[str] = Counter()
        event_map: dict[str, list[str]] = defaultdict(list)

        for event in current:
            for tech in event.technologies_mentioned or []:
                if tech and len(tech) > 2:
                    current_counts[tech] += 1
                    event_map[tech].append(str(event.id))

        prior_counts: Counter[str] = Counter()
        for event in prior:
            for tech in event.technologies_mentioned or []:
                if tech:
                    prior_counts[tech] += 1

        signals = []
        for tech, count in current_counts.most_common(10):
            if count < 2:
                continue
            prior_count = prior_counts.get(tech, 0)
            velocity = self._compute_velocity(count, prior_count)
            trend_score = self._compute_trend_score(count, velocity, len(current))

            signals.append({
                "trend_type": "technology",
                "name": tech,
                "slug": self._slugify(tech),
                "mention_count": count,
                "source_count": 0,
                "event_count": len(event_map[tech]),
                "previous_mention_count": prior_count,
                "trend_score": trend_score,
                "velocity": velocity,
                "is_emerging": prior_count == 0 and count >= 2,
                "related_event_ids": event_map[tech][:5],
                "top_headline": None,
            })

        return signals

    # ── Trend Persistence ──────────────────────────────────────────────────────

    async def _save_trend(
        self,
        signal: dict,
        window_hours: int,
        period_start: datetime,
        period_end: datetime,
    ) -> bool:
        """
        Save a trend signal to the DB.
        Returns True if created, False if updated.
        """
        # Try to find existing trend for this period
        stmt = select(Trend).where(
            Trend.trend_type == signal["trend_type"],
            Trend.slug == signal["slug"],
            Trend.period_hours == window_hours,
            Trend.period_start == period_start,
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update
            existing.mention_count = signal["mention_count"]
            existing.source_count = signal["source_count"]
            existing.event_count = signal["event_count"]
            existing.previous_mention_count = signal["previous_mention_count"]
            existing.trend_score = signal["trend_score"]
            existing.velocity = signal["velocity"]
            existing.is_emerging = signal["is_emerging"]
            existing.related_event_ids = signal.get("related_event_ids", [])
            existing.top_headline = signal.get("top_headline")
            return False
        else:
            # Create
            trend = Trend(
                trend_type=signal["trend_type"],
                name=signal["name"],
                slug=signal["slug"],
                period_hours=window_hours,
                period_start=period_start,
                period_end=period_end,
                mention_count=signal["mention_count"],
                source_count=signal["source_count"],
                event_count=signal["event_count"],
                previous_mention_count=signal["previous_mention_count"],
                trend_score=signal["trend_score"],
                velocity=signal["velocity"],
                is_emerging=signal["is_emerging"],
                related_event_ids=signal.get("related_event_ids", []),
                top_headline=signal.get("top_headline"),
            )
            self.db.add(trend)
            return True

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_velocity(current: int, prior: int) -> float:
        """
        Compute growth velocity as a percentage change.
        Returns value from -100 to +∞ (positive = trending up).
        """
        if prior == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - prior) / prior) * 100.0, 2)

    @staticmethod
    def _compute_trend_score(
        mention_count: int, velocity: float, total_events: int
    ) -> float:
        """
        Compute composite trend score (0–100).

        Combines absolute mentions (reach) and velocity (growth rate).
        """
        if total_events == 0:
            return 0.0

        # Reach: normalized mention count (logarithmic)
        reach = min(50.0, math.log(mention_count + 1, 2) * 10.0)

        # Velocity bonus: clamp velocity to [0, 200] then normalize to [0, 50]
        velocity_normalized = min(50.0, max(0.0, velocity) / 4.0)

        return round(min(100.0, reach + velocity_normalized), 2)

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert a string to a URL-safe slug."""
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug.strip("-")[:100]

    async def get_top_trends(
        self,
        trend_type: str | None = None,
        window_hours: int = 24,
        limit: int = 20,
    ) -> list[Trend]:
        """Fetch top trends from the DB for a given window."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours + 12)

        conditions = [
            Trend.period_hours == window_hours,
            Trend.period_start >= cutoff,
        ]
        if trend_type:
            conditions.append(Trend.trend_type == trend_type)

        stmt = (
            select(Trend)
            .where(and_(*conditions))
            .order_by(Trend.trend_score.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
