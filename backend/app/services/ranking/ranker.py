"""
AI Pulse – Ranking Engine
==========================
Computes final ranking scores for AI news articles.

Final Score = importance * 0.35 + trust * 0.30 + freshness * 0.20 + official * 0.15
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_article import NewsArticle
from app.utils.date_utils import freshness_score, utcnow

logger = get_logger(__name__)

# ── Weights ────────────────────────────────────────────────────────────────────
WEIGHT_IMPORTANCE = 0.35
WEIGHT_TRUST = 0.30
WEIGHT_FRESHNESS = 0.20
WEIGHT_OFFICIAL = 0.15

# Official source bonus (normalized to 0-100 scale)
OFFICIAL_SOURCE_SCORE = 100.0
UNOFFICIAL_SOURCE_SCORE = 40.0


def compute_final_score(
    importance_score: float,
    trust_score: float,
    published_at,
    is_official: bool,
) -> float:
    """
    Compute the weighted final ranking score for an article.

    All components are normalized to [0, 1] before weighting,
    then the result is scaled back to [0, 100].

    Args:
        importance_score: AI-assigned importance (0–100).
        trust_score: Trust/verification score (0–100).
        published_at: Article publication datetime (timezone-aware or naive UTC).
        is_official: Whether the article comes from an official company source.

    Returns:
        Final score in range [0.0, 100.0].
    """
    # Normalize to [0, 1]
    imp = importance_score / 100.0
    trust = trust_score / 100.0
    fresh = freshness_score(published_at) if published_at else 0.5
    official = 1.0 if is_official else UNOFFICIAL_SOURCE_SCORE / 100.0

    raw_score = (
        imp * WEIGHT_IMPORTANCE
        + trust * WEIGHT_TRUST
        + fresh * WEIGHT_FRESHNESS
        + official * WEIGHT_OFFICIAL
    )

    # Scale back to 0-100
    return round(min(100.0, raw_score * 100.0), 2)


class ArticleRanker:
    """
    Ranks articles by their final computed score.
    Also updates the final_score in the database.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def rank_and_update(self, article: NewsArticle) -> float:
        """
        Compute and save the final score for a single article.

        Args:
            article: NewsArticle ORM object (must have analysis loaded).

        Returns:
            Computed final score.
        """
        score = compute_final_score(
            importance_score=article.importance_score,
            trust_score=article.trust_score,
            published_at=article.published_at,
            is_official=article.is_official_source,
        )

        article.final_score = score
        return score

    async def rank_all_today(self) -> int:
        """
        Recompute final scores for all AI-processed articles from today.
        Called after the batch AI processing step.

        Returns:
            Number of articles ranked.
        """
        from app.utils.date_utils import start_of_day

        today_start = start_of_day()
        stmt = (
            select(NewsArticle)
            .where(
                NewsArticle.ai_processed == True,  # noqa: E712
                NewsArticle.is_duplicate == False,  # noqa: E712
                NewsArticle.is_verified == True,   # noqa: E712
                NewsArticle.created_at >= today_start,
            )
        )
        result = await self.db.execute(stmt)
        articles = list(result.scalars().all())

        count = 0
        for article in articles:
            score = compute_final_score(
                importance_score=article.importance_score,
                trust_score=article.trust_score,
                published_at=article.published_at,
                is_official=article.is_official_source,
            )
            article.final_score = score
            count += 1

        await self.db.commit()
        logger.info("articles_ranked", count=count)
        return count

    @staticmethod
    def sort_articles(articles: list[NewsArticle]) -> list[NewsArticle]:
        """
        Sort articles by final_score descending.
        Filters out articles below minimum threshold.
        """
        min_score = settings.min_final_score
        eligible = [a for a in articles if a.final_score >= min_score]
        return sorted(eligible, key=lambda a: a.final_score, reverse=True)
