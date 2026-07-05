"""
AI Pulse – Personalization Engine
====================================
Generates personalized daily briefs for each user
based on their preferences, favorite companies, and categories.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import DailyBrief
from app.models.news_article import NewsArticle
from app.models.news_analysis import NewsAnalysis
from app.models.user import User, UserPreferences
from app.utils.date_utils import start_of_day, today_utc

logger = get_logger(__name__)

# Preference boost weights
COMPANY_BOOST = 20.0
CATEGORY_BOOST = 15.0
TOPIC_KEYWORD_BOOST = 10.0
BLOCK_PENALTY = -1000.0  # Effectively removes the article


class PersonalizationEngine:
    """
    Generates personalized daily briefs for users.

    Algorithm:
    1. Fetch today's top verified, ranked articles (up to 50)
    2. For each user, load their preferences
    3. Apply boost/penalty scores based on preferences
    4. Re-rank with boosted scores
    5. Select min(all_high_quality, min_brief_articles) articles
    6. Store DailyBrief in database
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_todays_articles(self) -> list[NewsArticle]:
        """Fetch today's verified, AI-processed, non-duplicate articles."""
        today_start = start_of_day()
        min_trust = settings.min_trust_score

        stmt = (
            select(NewsArticle)
            .options(selectinload(NewsArticle.analysis))
            .where(
                NewsArticle.is_verified == True,  # noqa: E712
                NewsArticle.ai_processed == True,  # noqa: E712
                NewsArticle.is_duplicate == False,  # noqa: E712
                NewsArticle.trust_score >= min_trust,
                NewsArticle.created_at >= today_start,
            )
            .order_by(NewsArticle.final_score.desc())
            .limit(50)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def _personalize_score(
        self,
        article: NewsArticle,
        preferences: UserPreferences,
    ) -> float:
        """
        Compute a personalized score by boosting/penalizing based on preferences.
        """
        base_score = article.final_score
        analysis = article.analysis
        boost = 0.0

        if analysis:
            # Company boost
            article_companies_lower = {c.lower() for c in analysis.companies}
            for fav_company in preferences.favorite_companies:
                if fav_company.lower() in article_companies_lower:
                    boost += COMPANY_BOOST
                    break  # Only boost once per article

            # Category boost
            if analysis.category in preferences.favorite_categories:
                boost += CATEGORY_BOOST

            # Keyword/topic boost
            article_keywords_lower = {k.lower() for k in analysis.keywords + analysis.tags}
            for topic in preferences.favorite_topics:
                if topic.lower() in article_keywords_lower:
                    boost += TOPIC_KEYWORD_BOOST
                    break

            # Blocked topic penalty — removes article from brief
            combined_text = " ".join(
                analysis.keywords + analysis.tags + [analysis.category]
            ).lower()
            for blocked in preferences.blocked_topics:
                if blocked.lower() in combined_text:
                    boost += BLOCK_PENALTY
                    break

        return base_score + boost

    async def generate_brief_for_user(
        self,
        user_id: uuid.UUID,
        brief_date: date | None = None,
        articles: list[NewsArticle] | None = None,
    ) -> DailyBrief | None:
        """
        Generate a personalized daily brief for a single user.

        Args:
            user_id: The user's UUID.
            brief_date: Date for the brief (defaults to today UTC).
            articles: Pre-fetched article pool (avoids repeated DB queries).

        Returns:
            Created DailyBrief ORM object, or None if generation fails.
        """
        target_date = brief_date or today_utc()

        # Check if brief already exists for this user/date
        existing_stmt = select(DailyBrief).where(
            DailyBrief.user_id == user_id,
            DailyBrief.brief_date == target_date,
        )
        existing = await self.db.execute(existing_stmt)
        if existing.scalar_one_or_none():
            logger.debug("brief_already_exists", user_id=str(user_id), date=str(target_date))
            return None

        # Fetch preferences
        pref_stmt = select(UserPreferences).where(UserPreferences.user_id == user_id)
        pref_result = await self.db.execute(pref_stmt)
        preferences = pref_result.scalar_one_or_none()

        # Get articles
        pool = articles or await self.get_todays_articles()

        if not pool:
            logger.warning("no_articles_for_brief", user_id=str(user_id))
            return None

        # Score each article with user preferences
        if preferences:
            scored = [
                (article, self._personalize_score(article, preferences))
                for article in pool
            ]
        else:
            # No preferences — use base score
            scored = [(article, article.final_score) for article in pool]

        # Filter out blocked articles (score < 0) and sort descending
        scored = [(a, s) for a, s in scored if s >= 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Select articles for the brief
        min_count = settings.min_brief_articles
        selected = [a for a, _ in scored]

        # Ensure minimum article count
        if len(selected) < min_count:
            logger.warning(
                "insufficient_articles_for_brief",
                user_id=str(user_id),
                available=len(selected),
                minimum=min_count,
            )
            if not selected:
                return None

        # Compute personalization score (average boost applied)
        if scored:
            avg_personalization = sum(s - a.final_score for a, s in scored[:len(selected)]) / len(selected)
        else:
            avg_personalization = 0.0

        # Create brief
        brief = DailyBrief(
            user_id=user_id,
            brief_date=target_date,
            article_ids=[str(a.id) for a in selected],
            total_articles=len(selected),
            personalization_score=round(max(0.0, avg_personalization), 2),
        )
        self.db.add(brief)
        await self.db.flush()

        logger.info(
            "brief_generated",
            user_id=str(user_id),
            date=str(target_date),
            article_count=len(selected),
        )
        return brief

    async def generate_briefs_for_all_users(self) -> dict[str, int]:
        """
        Generate daily briefs for all active users with notifications enabled.
        Called by the daily scheduler.

        Returns:
            Stats dict: {generated, skipped, failed}.
        """
        # Fetch all articles once (shared pool)
        article_pool = await self.get_todays_articles()
        logger.info("brief_generation_started", article_pool_size=len(article_pool))

        if not article_pool:
            logger.warning("no_articles_available_for_briefs")
            return {"generated": 0, "skipped": 0, "failed": 0}

        # Get all active users
        user_stmt = select(User).where(User.is_active == True)  # noqa: E712
        user_result = await self.db.execute(user_stmt)
        users = list(user_result.scalars().all())

        generated = 0
        skipped = 0
        failed = 0

        for user in users:
            try:
                brief = await self.generate_brief_for_user(
                    user_id=user.id,
                    articles=article_pool,
                )
                if brief:
                    generated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.error(
                    "brief_generation_failed",
                    user_id=str(user.id),
                    error=str(exc),
                )
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
