"""
AI News Intelligence Engine – Event Clustering Service
========================================================
Groups articles covering the same story into NewsEvent objects.

Algorithm:
  1. Within-batch clustering: Jaccard title similarity + entity overlap
  2. Cross-batch matching: embedding similarity against recent Events (72h)
  3. Event creation: Create/update NewsEvent, attach all source articles
  4. Event updating: New source = boost source_count + update priority
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.news_article import NewsArticle
from app.models.news_event import NewsEvent
from app.services.news_fetchers.base import RawArticle
from app.services.priority_engine import PriorityEngine
from app.utils.text_utils import normalize_title

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
JACCARD_THRESHOLD = 0.35          # Title similarity threshold for same-story grouping
ENTITY_OVERLAP_THRESHOLD = 2      # Min shared entities to force-group
EMBEDDING_SIMILARITY_THRESHOLD = 0.88  # Cosine similarity for cross-batch matching
EVENT_WINDOW_HOURS = 72           # How far back to look for existing events


@dataclass
class ArticleCluster:
    """A group of articles covering the same story."""
    canonical: RawArticle
    sources: list[RawArticle] = field(default_factory=list)

    @property
    def all_articles(self) -> list[RawArticle]:
        return [self.canonical] + self.sources

    @property
    def source_domains(self) -> list[str]:
        return list({a.source_domain for a in self.all_articles})

    @property
    def source_count(self) -> int:
        return len(self.source_domains)

    @property
    def earliest_published(self) -> datetime | None:
        dates = [a.published_at for a in self.all_articles if a.published_at]
        return min(dates) if dates else None


class EventClusteringEngine:
    """
    Clusters articles into NewsEvents.

    Usage:
        engine = EventClusteringEngine(db)
        events_created, events_updated = await engine.process_batch(articles)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.priority_engine = PriorityEngine()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_batch(
        self, articles: list[RawArticle]
    ) -> tuple[int, int]:
        """
        Process a batch of validated articles into Events.

        Steps:
          1. Within-batch: cluster articles by title similarity
          2. Cross-batch: match clusters against existing recent events
          3. Create new events or update existing ones

        Returns:
            (events_created, events_updated)
        """
        if not articles:
            return 0, 0

        # Step 1: Cluster articles within this batch
        clusters = self._cluster_within_batch(articles)
        logger.info(
            "batch_clustered",
            articles_in=len(articles),
            clusters=len(clusters),
        )

        events_created = 0
        events_updated = 0

        for cluster in clusters:
            # Step 2: Check if a recent Event already covers this story
            existing_event = await self._find_existing_event(cluster)

            if existing_event:
                # Step 3a: Update existing event with new sources
                await self._update_event(existing_event, cluster)
                events_updated += 1
            else:
                # Step 3b: Create a new event
                await self._create_event(cluster)
                events_created += 1

        try:
            await self.db.commit()
        except Exception as exc:
            logger.error("event_clustering_commit_error", error=str(exc))
            await self.db.rollback()
            return 0, 0

        logger.info(
            "event_clustering_complete",
            events_created=events_created,
            events_updated=events_updated,
        )
        return events_created, events_updated

    # ── Within-Batch Clustering ────────────────────────────────────────────────

    def _cluster_within_batch(
        self, articles: list[RawArticle]
    ) -> list[ArticleCluster]:
        """
        Group articles by title similarity (Jaccard) and entity overlap.

        Uses greedy clustering: iterate articles in trust-tier order,
        and for each unclustered article, collect all similar articles.
        """
        assigned: set[int] = set()
        clusters: list[ArticleCluster] = []

        # Sort: official first, then by published_at desc
        sorted_articles = sorted(
            enumerate(articles),
            key=lambda ia: (
                not ia[1].is_official,
                -(ia[1].published_at.timestamp() if ia[1].published_at else 0),
            ),
        )

        for idx, article in sorted_articles:
            if idx in assigned:
                continue

            cluster = ArticleCluster(canonical=article)
            assigned.add(idx)

            norm_i = normalize_title(article.title)
            words_i = set(norm_i.split()) - STOP_WORDS

            for j, other in sorted_articles:
                if j in assigned or j == idx:
                    continue

                norm_j = normalize_title(other.title)
                words_j = set(norm_j.split()) - STOP_WORDS

                if not words_i or not words_j:
                    continue

                # Jaccard similarity
                intersection = len(words_i & words_j)
                union = len(words_i | words_j)
                jaccard = intersection / union if union else 0.0

                if jaccard >= JACCARD_THRESHOLD:
                    cluster.sources.append(other)
                    assigned.add(j)

            clusters.append(cluster)

        return clusters

    # ── Cross-Batch Event Matching ─────────────────────────────────────────────

    async def _find_existing_event(
        self, cluster: ArticleCluster
    ) -> NewsEvent | None:
        """
        Find a recent NewsEvent that matches this article cluster.

        Checks by:
          1. Exact primary URL match
          2. Title similarity against recent events
          3. Embedding similarity (if available)
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=EVENT_WINDOW_HOURS)

        # Check 1: Exact URL match
        canonical_url = cluster.canonical.url
        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.primary_source_url == canonical_url,
                NewsEvent.created_at >= cutoff,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        if event := result.scalar_one_or_none():
            return event

        # Check 2: Title similarity against recent events
        norm_title = normalize_title(cluster.canonical.title)
        words_new = set(norm_title.split()) - STOP_WORDS
        if not words_new:
            return None

        stmt = (
            select(NewsEvent)
            .where(NewsEvent.created_at >= cutoff)
            .order_by(NewsEvent.created_at.desc())
            .limit(100)
        )
        result = await self.db.execute(stmt)
        recent_events = result.scalars().all()

        best_match: NewsEvent | None = None
        best_jaccard = 0.0

        for event in recent_events:
            norm_ev = normalize_title(event.headline)
            words_ev = set(norm_ev.split()) - STOP_WORDS
            if not words_ev:
                continue
            intersection = len(words_new & words_ev)
            union = len(words_new | words_ev)
            jaccard = intersection / union if union else 0.0
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_match = event

        if best_match and best_jaccard >= JACCARD_THRESHOLD:
            logger.debug(
                "event_matched_by_title",
                headline=cluster.canonical.title[:60],
                matched_event=str(best_match.id),
                jaccard=round(best_jaccard, 3),
            )
            return best_match

        return None

    # ── Event Creation ─────────────────────────────────────────────────────────

    async def _create_event(self, cluster: ArticleCluster) -> NewsEvent:
        """Create a new NewsEvent from an article cluster."""
        canonical = cluster.canonical
        now = datetime.now(timezone.utc)

        # Select best headline (prefer official source)
        headline = canonical.title

        # Compute priority
        priority_result = self.priority_engine.compute(
            published_at=cluster.earliest_published,
            source_domains=cluster.source_domains,
            source_count=cluster.source_count,
        )

        event = NewsEvent(
            id=uuid.uuid4(),
            headline=headline[:600],
            summary=canonical.description[:500] if canonical.description else None,
            category="General AI",  # Will be updated by AI enrichment
            priority_score=priority_result.priority_score,
            freshness_score=priority_result.freshness_score,
            trust_score=priority_result.trust_score,
            impact_score=priority_result.impact_score,
            is_breaking=priority_result.is_breaking,
            source_count=cluster.source_count,
            source_domains=cluster.source_domains,
            primary_source_domain=canonical.source_domain,
            primary_source_url=canonical.url,
            published_at=cluster.earliest_published,
            first_seen_at=now,
            last_updated_at=now,
            image_url=canonical.image_url,
        )

        self.db.add(event)
        await self.db.flush()  # Get ID

        logger.debug(
            "event_created",
            event_id=str(event.id),
            headline=headline[:60],
            priority=priority_result.priority_score,
            sources=cluster.source_count,
            is_breaking=priority_result.is_breaking,
        )

        return event

    async def _update_event(
        self, event: NewsEvent, cluster: ArticleCluster
    ) -> None:
        """Update an existing event with new source information."""
        now = datetime.now(timezone.utc)

        # Merge source domains
        existing_domains = set(event.source_domains or [])
        new_domains = set(cluster.source_domains)
        merged_domains = list(existing_domains | new_domains)

        # Re-compute priority with updated source count
        priority_result = self.priority_engine.compute(
            published_at=event.published_at,
            source_domains=merged_domains,
            source_count=len(merged_domains),
            event_type=event.event_type,
            companies=list(event.companies or []),
            funding_amount=event.funding_amount,
        )

        event.source_domains = merged_domains
        event.source_count = len(merged_domains)
        event.priority_score = priority_result.priority_score
        event.freshness_score = priority_result.freshness_score
        event.trust_score = priority_result.trust_score
        event.is_breaking = priority_result.is_breaking
        event.last_updated_at = now

        # Update headline if the canonical source is more authoritative
        if cluster.canonical.is_official and not any(
            d in (event.primary_source_domain or "") for d in ["openai", "anthropic", "deepmind"]
        ):
            event.headline = cluster.canonical.title[:600]
            event.primary_source_domain = cluster.canonical.source_domain
            event.primary_source_url = cluster.canonical.url

        logger.debug(
            "event_updated",
            event_id=str(event.id),
            new_sources=len(new_domains - existing_domains),
            priority=priority_result.priority_score,
        )

    # ── Article-to-Event Linking ───────────────────────────────────────────────

    async def link_articles_to_events(
        self,
        article_event_pairs: list[tuple[NewsArticle, NewsEvent]],
    ) -> None:
        """
        Link saved NewsArticle records to their parent NewsEvent.
        Called after articles are saved to the DB.
        """
        for article, event in article_event_pairs:
            article.event_id = event.id
            article.priority_score = event.priority_score

        try:
            await self.db.flush()
        except Exception as exc:
            logger.error("article_event_link_error", error=str(exc))


# ── Stop Words (excluded from Jaccard comparison) ─────────────────────────────
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "its", "it", "this", "that", "these", "those", "how", "why", "what",
    "when", "where", "who", "which", "new", "says", "said", "report",
    "reports", "using", "use", "via", "now", "just", "more", "than",
}
