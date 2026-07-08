"""
AI Pulse - Personalization Engine
=================================
Builds bounded, diverse daily briefs for each user.

The old implementation added static preference boosts directly to article
scores and then tried to satisfy a minimum count. This module replaces that
with a quality threshold, saturating affinity, recency-weighted bookmark
telemetry, coverage-aware re-ranking, per-tag quotas, and exploration slots.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Bookmark, DailyBrief
from app.models.news_article import NewsArticle
from app.models.user import User, UserPreferences
from app.utils.date_utils import freshness_score, start_of_day, today_utc, utcnow

logger = get_logger(__name__)

MAJOR_TREND_THRESHOLD = 85.0

TELEMETRY_WEIGHTS = {
    "bookmark": 5.0,
    "explicit_topic": 3.0,
    "explicit_category": 3.5,
    "explicit_company": 2.5,
}

TOPIC_EXPANSIONS = {
    "pytorch": ["deep learning", "ml frameworks", "torch", "model training"],
    "mcp": ["model context protocol", "agents", "tool calling", "developer tools"],
    "rag": ["retrieval", "embeddings", "vector database", "knowledge systems"],
    "agents": ["ai agents", "tool use", "workflows", "autonomous systems"],
    "quantization": ["model compression", "inference optimization", "edge ai"],
    "llms": ["language models", "reasoning", "model releases", "nlp"],
}


@dataclass(frozen=True)
class ScoredArticle:
    article: NewsArticle
    personalized_score: float
    quality_score: float
    affinity_score: float
    base_trend_score: float
    primary_tag: str
    tags: set[str]
    reason: str
    is_serendipity: bool = False


def _normalize_term(value: str | None) -> str:
    return (value or "").strip().lower()


def _article_tags(article: NewsArticle) -> set[str]:
    analysis = article.analysis
    terms: set[str] = set()

    if analysis:
        fields: Iterable[str | None] = (
            [analysis.category, analysis.subcategory, analysis.event_type]
            + list(analysis.tags or [])
            + list(analysis.keywords or [])
            + list(analysis.companies or [])
            + list(analysis.products_mentioned or [])
            + list(analysis.technologies_mentioned or [])
            + list(analysis.models_mentioned or [])
            + list(analysis.programming_languages or [])
        )
        terms.update(t for t in (_normalize_term(v) for v in fields) if t)

    terms.update(t for t in (_normalize_term(v) for v in [article.source_domain]) if t)
    return terms


def _primary_tag(article: NewsArticle) -> str:
    analysis = article.analysis
    if analysis and analysis.category:
        return _normalize_term(analysis.category)
    tags = sorted(_article_tags(article))
    return tags[0] if tags else "general ai"


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _tag_entropy(items: list[ScoredArticle]) -> float:
    if not items:
        return 0.0
    counts = Counter(item.primary_tag for item in items)
    total = len(items)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log(p, 2)
    return round(entropy, 3)


class PersonalizationEngine:
    """
    Generates personalized daily briefs.

    Scoring formula, units, and ranges:
      - base_trend_score: article.priority_score or final_score, range 0-100.
        This is the global "important for everyone" signal.
      - trust_score: verified source confidence, range 0-100.
      - importance_score: AI article/event importance, range 0-100.
      - recency: exponential freshness in [0, 1], converted to 0-100.
      - quality_score = 0.52*base_trend + 0.20*trust + 0.18*importance
        + 0.10*(recency*100). Expected range 0-100.
      - affinity_score: saturating user interest in [0, 1]. Raw explicit and
        bookmark telemetry weights are recency-decayed with a 14-day half-life,
        summed per tag, then transformed with 1 - exp(-sum/4). This prevents
        permanent, unbounded single-topic dominance.
      - personalized_score = quality*(0.70 + 0.30*affinity) + 12*affinity.
        Major global stories cannot be suppressed below 72% of base_trend_score.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_todays_articles(self) -> list[NewsArticle]:
        """Fetch today's verified, AI-processed, non-duplicate articles."""
        today_start = start_of_day()
        stmt = (
            select(NewsArticle)
            .options(selectinload(NewsArticle.analysis))
            .where(
                NewsArticle.is_verified == True,  # noqa: E712
                NewsArticle.ai_processed == True,  # noqa: E712
                NewsArticle.is_duplicate == False,  # noqa: E712
                NewsArticle.trust_score >= settings.min_trust_score,
                NewsArticle.created_at >= today_start,
            )
            .order_by(NewsArticle.priority_score.desc(), NewsArticle.final_score.desc())
            .limit(200)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _load_preferences(self, user_id: uuid.UUID) -> UserPreferences | None:
        result = await self.db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def _cold_start_affinity(
        self,
        user: User | None,
        preferences: UserPreferences | None,
    ) -> dict[str, float]:
        """
        Seed affinity before behavioral telemetry exists.

        Today the schema stores explicit companies/categories/topics. If future
        columns such as job_title or tech_stack are added, they are picked up via
        getattr here without changing the feed contract. Topic expansion is a
        deterministic local fallback for the LLM signup expansion described in
        the product spec; the async signup path can replace or augment this map.
        """
        vector: dict[str, float] = defaultdict(float)
        if not preferences:
            return vector

        for category in preferences.favorite_categories or []:
            vector[_normalize_term(category)] += TELEMETRY_WEIGHTS["explicit_category"]
        for company in preferences.favorite_companies or []:
            vector[_normalize_term(company)] += TELEMETRY_WEIGHTS["explicit_company"]
        for topic in preferences.favorite_topics or []:
            normalized = _normalize_term(topic)
            vector[normalized] += TELEMETRY_WEIGHTS["explicit_topic"]
            for expanded in TOPIC_EXPANSIONS.get(normalized, []):
                vector[expanded] += TELEMETRY_WEIGHTS["explicit_topic"] * 0.55

        profile_terms = []
        for attr in ("job_title", "tech_stack", "onboarding_topics"):
            value = getattr(user, attr, None) if user is not None else None
            if isinstance(value, str):
                profile_terms.extend(part.strip() for part in value.split(","))
            elif isinstance(value, list):
                profile_terms.extend(str(part) for part in value)

        for term in profile_terms:
            normalized = _normalize_term(term)
            if normalized:
                vector[normalized] += 1.5

        return dict(vector)

    async def _bookmark_affinity(self, user_id: uuid.UUID) -> dict[str, float]:
        cutoff = utcnow() - timedelta(days=settings.telemetry_retention_days)
        stmt = (
            select(Bookmark)
            .options(selectinload(Bookmark.article).selectinload(NewsArticle.analysis))
            .where(
                Bookmark.user_id == user_id,
                Bookmark.created_at >= cutoff,
            )
            .limit(500)
        )
        result = await self.db.execute(stmt)
        bookmarks = list(result.scalars().all())

        half_life = settings.telemetry_half_life_days
        vector: dict[str, float] = defaultdict(float)
        for bookmark in bookmarks:
            article = bookmark.article
            if not article:
                continue
            age_days = max(
                0.0,
                (utcnow() - bookmark.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 86400,
            )
            decay = 0.5 ** (age_days / half_life)
            for term in _article_tags(article):
                vector[term] += TELEMETRY_WEIGHTS["bookmark"] * decay

        return dict(vector)

    async def _build_affinity_vector(
        self,
        user_id: uuid.UUID,
        preferences: UserPreferences | None,
    ) -> dict[str, float]:
        user = None
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        vector = defaultdict(float, self._cold_start_affinity(user, preferences))
        for term, value in (await self._bookmark_affinity(user_id)).items():
            vector[term] += value
        return dict(vector)

    @staticmethod
    def _saturating_affinity(article_terms: set[str], vector: dict[str, float]) -> float:
        raw = sum(vector.get(term, 0.0) for term in article_terms)
        return round(1.0 - math.exp(-raw / 4.0), 4)

    def _blocked(self, article: NewsArticle, preferences: UserPreferences | None) -> bool:
        if not preferences or not preferences.blocked_topics:
            return False
        haystack = set(_article_tags(article))
        title_text = _normalize_term(article.title)
        return any(
            _normalize_term(blocked) in haystack
            or _normalize_term(blocked) in title_text
            for blocked in preferences.blocked_topics
        )

    def score_article(
        self,
        article: NewsArticle,
        affinity_vector: dict[str, float],
        preferences: UserPreferences | None = None,
    ) -> ScoredArticle | None:
        if self._blocked(article, preferences):
            return None

        base_trend = max(float(article.priority_score or 0.0), float(article.final_score or 0.0))
        importance = float(article.importance_score or 0.0)
        trust = float(article.trust_score or 0.0)
        recency = freshness_score(article.published_at) if article.published_at else 0.5

        quality = (
            base_trend * 0.52
            + trust * 0.20
            + importance * 0.18
            + (recency * 100.0) * 0.10
        )

        tags = _article_tags(article)
        affinity = self._saturating_affinity(tags, affinity_vector)
        personalized = quality * (0.70 + 0.30 * affinity) + (12.0 * affinity)

        if base_trend >= MAJOR_TREND_THRESHOLD:
            personalized = max(personalized, base_trend * 0.72)

        reason = "global trend override" if base_trend >= MAJOR_TREND_THRESHOLD else "profile affinity"
        if affinity == 0:
            reason = "quality threshold"

        return ScoredArticle(
            article=article,
            personalized_score=round(min(100.0, personalized), 2),
            quality_score=round(min(100.0, quality), 2),
            affinity_score=affinity,
            base_trend_score=round(base_trend, 2),
            primary_tag=_primary_tag(article),
            tags=tags,
            reason=reason,
        )

    def _select_serendipity(
        self,
        candidates: list[ScoredArticle],
        affinity_vector: dict[str, float],
        slots: int,
    ) -> list[ScoredArticle]:
        if slots <= 0:
            return []
        underexplored = [
            item for item in candidates
            if item.primary_tag not in affinity_vector
            and item.quality_score >= settings.brief_min_quality_score
        ]
        underexplored.sort(key=lambda i: (i.quality_score, i.base_trend_score), reverse=True)
        return [
            ScoredArticle(
                article=item.article,
                personalized_score=item.personalized_score,
                quality_score=item.quality_score,
                affinity_score=item.affinity_score,
                base_trend_score=item.base_trend_score,
                primary_tag=item.primary_tag,
                tags=item.tags,
                reason="serendipity",
                is_serendipity=True,
            )
            for item in underexplored[:slots]
        ]

    def diversify(
        self,
        scored: list[ScoredArticle],
        affinity_vector: dict[str, float],
        user_id: uuid.UUID | None = None,
    ) -> list[ScoredArticle]:
        eligible = [
            item for item in scored
            if item.personalized_score >= settings.brief_min_quality_score
            or item.base_trend_score >= MAJOR_TREND_THRESHOLD
        ]
        eligible.sort(key=lambda i: i.personalized_score, reverse=True)
        if not eligible:
            return []

        hard_max = settings.brief_hard_max_articles
        soft_max = settings.brief_soft_max_articles
        target = min(len(eligible), hard_max if len(eligible) > soft_max else len(eligible))
        quota = max(1, math.ceil(target * settings.brief_max_tag_share))

        seed = f"{user_id or 'anon'}:{today_utc().isoformat()}".encode("utf-8")
        deterministic_slots = settings.brief_serendipity_slots
        if int(hashlib.sha256(seed).hexdigest(), 16) % 3 == 0:
            deterministic_slots = max(1, deterministic_slots - 1)
        serendipity = self._select_serendipity(eligible, affinity_vector, deterministic_slots)
        reserved_ids = {str(item.article.id) for item in serendipity}

        selected: list[ScoredArticle] = []
        tag_counts: Counter[str] = Counter()

        def can_add(item: ScoredArticle) -> bool:
            return tag_counts[item.primary_tag] < quota

        while len(selected) < max(0, target - len(serendipity)):
            best: ScoredArticle | None = None
            best_score = -1e9
            for item in eligible:
                if str(item.article.id) in reserved_ids:
                    continue
                if any(item.article.id == chosen.article.id for chosen in selected):
                    continue
                if not can_add(item):
                    continue
                redundancy = max((_jaccard(item.tags, chosen.tags) for chosen in selected), default=0.0)
                novelty_bonus = 4.0 if tag_counts[item.primary_tag] == 0 else 0.0
                mmr_score = item.personalized_score * 0.86 - redundancy * 22.0 + novelty_bonus
                if mmr_score > best_score:
                    best = item
                    best_score = mmr_score
            if best is None:
                break
            selected.append(best)
            tag_counts[best.primary_tag] += 1

        for item in serendipity:
            if len(selected) >= target:
                break
            if not any(item.article.id == chosen.article.id for chosen in selected) and can_add(item):
                selected.append(item)
                tag_counts[item.primary_tag] += 1

        selected.sort(
            key=lambda item: (
                item.is_serendipity,
                -item.personalized_score,
                -item.base_trend_score,
            )
        )
        logger.info(
            "brief_diversity_metrics",
            user_id=str(user_id) if user_id else None,
            candidate_count=len(scored),
            eligible_count=len(eligible),
            selected_count=len(selected),
            category_coverage=len({item.primary_tag for item in selected}),
            tag_entropy=_tag_entropy(selected),
            tag_counts=dict(tag_counts),
            serendipity_count=sum(1 for item in selected if item.is_serendipity),
        )
        return selected

    async def generate_brief_for_user(
        self,
        user_id: uuid.UUID,
        brief_date: date | None = None,
        articles: list[NewsArticle] | None = None,
        force: bool = False,
    ) -> DailyBrief | None:
        target_date = brief_date or today_utc()

        existing_stmt = select(DailyBrief).where(
            DailyBrief.user_id == user_id,
            DailyBrief.brief_date == target_date,
        )
        existing_result = await self.db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        if existing and not force:
            logger.debug("brief_already_exists", user_id=str(user_id), date=str(target_date))
            return None

        preferences = await self._load_preferences(user_id)
        pool = articles or await self.get_todays_articles()
        if not pool:
            logger.warning("no_articles_for_brief", user_id=str(user_id))
            return None

        affinity_vector = await self._build_affinity_vector(user_id, preferences)
        scored = [
            item for item in (
                self.score_article(article, affinity_vector, preferences)
                for article in pool
            )
            if item is not None
        ]

        selected = self.diversify(scored, affinity_vector, user_id=user_id)
        if not selected:
            logger.info("no_quality_matches_for_brief", user_id=str(user_id))
            if existing and force:
                existing.article_ids = []
                existing.total_articles = 0
                existing.personalization_score = 0.0
                existing.notification_sent = False
                existing.sent_at = None
                await self.db.flush()
                await self.invalidate_brief_cache(user_id)
                return existing
            return None

        avg_personalization = sum(item.affinity_score for item in selected) / len(selected)
        article_ids = [str(item.article.id) for item in selected]

        if existing:
            existing.article_ids = article_ids
            existing.total_articles = len(article_ids)
            existing.personalization_score = round(avg_personalization * 100.0, 2)
            existing.notification_sent = False
            existing.sent_at = None
            brief = existing
        else:
            brief = DailyBrief(
                user_id=user_id,
                brief_date=target_date,
                article_ids=article_ids,
                total_articles=len(article_ids),
                personalization_score=round(avg_personalization * 100.0, 2),
            )
            self.db.add(brief)

        await self.db.flush()
        await self.invalidate_brief_cache(user_id)
        logger.info(
            "brief_generated",
            user_id=str(user_id),
            date=str(target_date),
            article_count=len(article_ids),
            force=force,
        )
        return brief

    async def regenerate_after_profile_change(self, user_id: uuid.UUID) -> DailyBrief | None:
        """Invalidate cache and rebuild today's brief after preference/profile edits."""
        await self.invalidate_brief_cache(user_id)
        return await self.generate_brief_for_user(user_id, force=True)

    async def incorporate_breaking_delta(
        self,
        user_id: uuid.UUID,
        delta_articles: list[NewsArticle],
    ) -> DailyBrief | None:
        """
        Cheap interrupt path: score new breaking candidates and merge them into
        today's existing brief instead of recomputing every article from scratch.
        """
        if not delta_articles:
            return None

        today = today_utc()
        existing_result = await self.db.execute(
            select(DailyBrief).where(
                DailyBrief.user_id == user_id,
                DailyBrief.brief_date == today,
            )
        )
        existing = existing_result.scalar_one_or_none()
        existing_articles: list[NewsArticle] = []
        if existing and existing.article_ids:
            article_ids = [uuid.UUID(str(aid)) for aid in existing.article_ids]
            article_result = await self.db.execute(
                select(NewsArticle)
                .options(selectinload(NewsArticle.analysis))
                .where(NewsArticle.id.in_(article_ids))
            )
            existing_articles = list(article_result.scalars().all())

        merged = {str(article.id): article for article in existing_articles}
        for article in delta_articles:
            if max(article.priority_score or 0.0, article.final_score or 0.0) >= settings.breaking_interrupt_threshold:
                merged[str(article.id)] = article

        if len(merged) == len(existing_articles):
            return existing
        return await self.generate_brief_for_user(user_id, articles=list(merged.values()), force=True)

    async def invalidate_brief_cache(self, user_id: uuid.UUID) -> None:
        try:
            from app.services.cache.redis_client import get_redis_client
            redis = get_redis_client()
            await redis.delete(f"brief:today:{user_id}")
        except Exception as exc:
            logger.debug("brief_cache_invalidation_failed", user_id=str(user_id), error=str(exc))

    async def generate_briefs_for_all_users(self) -> dict[str, int]:
        article_pool = await self.get_todays_articles()
        logger.info("brief_generation_started", article_pool_size=len(article_pool))
        if not article_pool:
            logger.warning("no_articles_available_for_briefs")
            return {"generated": 0, "skipped": 0, "failed": 0}

        user_stmt = select(User).where(User.is_active == True)  # noqa: E712
        user_result = await self.db.execute(user_stmt)
        users = list(user_result.scalars().all())

        generated = skipped = failed = 0
        for user in users:
            try:
                brief = await self.generate_brief_for_user(user.id, articles=article_pool)
                if brief:
                    generated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.error("brief_generation_failed", user_id=str(user.id), error=str(exc))
                failed += 1

        await self.db.commit()
        logger.info(
            "brief_generation_complete",
            total_users=len(users),
            generated=generated,
            skipped=skipped,
            failed=failed,
        )
        return {"generated": generated, "skipped": skipped, "failed": failed}
