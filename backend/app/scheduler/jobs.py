"""
AI Pulse – Scheduler Job Implementations
==========================================
Async job functions executed by APScheduler.
Each job gets its own DB session and handles its own cleanup.
"""

from __future__ import annotations

import json
import uuid

from app.core.logging import get_logger
from app.utils.date_utils import days_ago, utcnow

logger = get_logger(__name__)


async def job_fetch_and_process_news() -> None:
    """
    Main daily pipeline job:
    1. Fetch news from all sources
    2. Normalize articles
    3. Run duplicate detection
    4. Run verification
    5. Save to database
    6. Run AI analysis (Gemini)
    7. Rank all articles
    8. Generate personalized briefs for all users
    """
    logger.info("job_started", job="fetch_and_process_news")
    start = utcnow()

    from app.database.connection import AsyncSessionLocal
    from app.models.news_article import NewsArticle
    from app.models.news_source import NewsSource
    from app.services.ai.analyzer import BatchArticleProcessor
    from app.services.duplicate_detection.engine import DuplicateDetectionEngine
    from app.services.news_fetchers.orchestrator import NewsFetchOrchestrator
    from app.services.personalization.engine import PersonalizationEngine
    from app.services.ranking.ranker import ArticleRanker
    from app.services.verification.engine import VerificationEngine
    from app.utils.text_utils import (
        content_fingerprint,
        entity_fingerprint,
        normalize_title,
        normalize_url,
        title_fingerprint,
        extract_domain,
    )

    stats = {
        "fetched": 0,
        "verified": 0,
        "duplicates": 0,
        "saved": 0,
        "ai_processed": 0,
        "ranked": 0,
        "briefs_generated": 0,
    }

    try:
        # ── Step 1: Fetch from all sources ────────────────────────────────────
        orchestrator = NewsFetchOrchestrator()
        raw_articles = await orchestrator.fetch_all()
        stats["fetched"] = len(raw_articles)
        logger.info("fetch_complete", count=len(raw_articles))

        # ── Step 2: Verify and cross-reference ────────────────────────────────
        verification_engine = VerificationEngine()
        verified_articles = verification_engine.verify_batch(raw_articles)
        stats["verified"] = sum(1 for _, r in verified_articles if r.is_verified)

        # ── Step 3: Deduplicate and save to DB ────────────────────────────────
        async with AsyncSessionLocal() as db:
            dup_engine = DuplicateDetectionEngine(db)
            saved_articles = []

            # 1. Filter out duplicates first
            unique_articles_to_import = []
            for raw, trust_result in verified_articles:
                if not trust_result.is_verified:
                    continue

                # Run duplicate detection
                dup_result = await dup_engine.check(raw)
                if dup_result.is_duplicate:
                    stats["duplicates"] += 1
                    # Update supporting sources on canonical article
                    if dup_result.canonical_id:
                        from sqlalchemy import select
                        stmt = select(NewsArticle).where(
                            NewsArticle.id == uuid.UUID(dup_result.canonical_id)
                        )
                        result = await db.execute(stmt)
                        canonical = result.scalar_one_or_none()
                        if canonical and raw.url not in canonical.supporting_sources:
                            canonical.supporting_sources = list(canonical.supporting_sources) + [raw.url]
                    continue

                unique_articles_to_import.append((raw, trust_result))

            # 2. Get embeddings for all unique articles concurrently
            if unique_articles_to_import:
                from app.services.ai.gemini_client import get_gemini_client
                import asyncio
                client = get_gemini_client()

                async def get_emb_for_raw(raw_item):
                    try:
                        return await client.generate_embedding(raw_item.title)
                    except Exception as e:
                        logger.warning("embedding_generation_failed", title=raw_item.title[:40], error=str(e))
                        return None

                embeddings = await asyncio.gather(*(get_emb_for_raw(raw) for raw, _ in unique_articles_to_import))

                # 3. Create article records and insert
                for (raw, trust_result), embedding in zip(unique_articles_to_import, embeddings):
                    norm_url = normalize_url(raw.url)
                    norm_title = normalize_title(raw.title)
                    t_fp = title_fingerprint(raw.title)
                    c_fp = content_fingerprint(raw.title, raw.content_snippet or "")
                    embedding_json = json.dumps(embedding) if embedding else None

                    article = NewsArticle(
                        title=raw.title,
                        normalized_title=norm_title,
                        url=raw.url,
                        normalized_url=norm_url,
                        image_url=raw.image_url,
                        description=raw.description,
                        content_snippet=raw.content_snippet,
                        author=raw.author,
                        published_at=raw.published_at,
                        source_domain=raw.source_domain,
                        title_fingerprint=t_fp,
                        content_fingerprint=c_fp,
                        embedding_json=embedding_json,
                        is_duplicate=False,
                        is_verified=trust_result.is_verified,
                        trust_score=trust_result.trust_score,
                        verification_notes=trust_result.notes,
                        is_official_source=raw.is_official,
                        supporting_sources=[],
                    )
                    db.add(article)
                    saved_articles.append(article)
                    stats["saved"] += 1

            await db.commit()
            logger.info("articles_saved", count=stats["saved"])

            # ── Step 4: AI processing (Gemini) ────────────────────────────────
            if saved_articles:
                # Refresh articles from DB
                from sqlalchemy import select as sa_select
                article_ids = [a.id for a in saved_articles]
                stmt = sa_select(NewsArticle).where(
                    NewsArticle.id.in_(article_ids)
                )
                result = await db.execute(stmt)
                articles_for_ai = list(result.scalars().all())

                processor = BatchArticleProcessor(db)
                ai_stats = await processor.process_batch(articles_for_ai)
                stats["ai_processed"] = ai_stats["processed"]

            # ── Step 5: Rank articles ─────────────────────────────────────────
            ranker = ArticleRanker(db)
            stats["ranked"] = await ranker.rank_all_today()

            # ── Step 6: Generate personalized briefs ──────────────────────────
            personalization = PersonalizationEngine(db)
            brief_stats = await personalization.generate_briefs_for_all_users()
            stats["briefs_generated"] = brief_stats["generated"]

        duration = (utcnow() - start).total_seconds()
        logger.info(
            "job_completed",
            job="fetch_and_process_news",
            duration_seconds=round(duration, 1),
            **stats,
        )

    except Exception as exc:
        logger.error(
            "job_failed",
            job="fetch_and_process_news",
            error=str(exc),
            exc_info=True,
        )


async def job_send_notifications() -> None:
    """Send daily brief push notifications to all eligible users."""
    logger.info("job_started", job="send_notifications")

    try:
        from app.database.connection import AsyncSessionLocal
        from app.services.notifications.fcm_client import DailyNotificationSender

        async with AsyncSessionLocal() as db:
            sender = DailyNotificationSender(db)
            stats = await sender.send_all()

        logger.info("job_completed", job="send_notifications", **stats)

    except Exception as exc:
        logger.error(
            "job_failed",
            job="send_notifications",
            error=str(exc),
            exc_info=True,
        )


async def job_cleanup_old_articles() -> None:
    """Delete articles older than CLEANUP_DAYS_OLD days."""
    logger.info("job_started", job="cleanup_old_articles")

    try:
        from sqlalchemy import delete as sa_delete
        from app.database.connection import AsyncSessionLocal
        from app.models.news_article import NewsArticle
        from app.core.config import settings

        cutoff = days_ago(settings.cleanup_days_old)

        async with AsyncSessionLocal() as db:
            stmt = sa_delete(NewsArticle).where(
                NewsArticle.created_at < cutoff
            )
            result = await db.execute(stmt)
            await db.commit()
            deleted = result.rowcount

        logger.info(
            "job_completed",
            job="cleanup_old_articles",
            deleted_articles=deleted,
            cutoff_days=settings.cleanup_days_old,
        )

    except Exception as exc:
        logger.error(
            "job_failed",
            job="cleanup_old_articles",
            error=str(exc),
            exc_info=True,
        )


async def job_refresh_source_health() -> None:
    """
    Test all active news sources and update their health status.
    Disables sources with 5+ consecutive failures.
    """
    logger.info("job_started", job="refresh_source_health")

    try:
        from sqlalchemy import select
        from app.database.connection import AsyncSessionLocal
        from app.models.news_source import NewsSource
        from app.utils.http_client import fetch_with_retry
        from app.core.exceptions import FetchError

        async with AsyncSessionLocal() as db:
            stmt = select(NewsSource).where(NewsSource.is_active == True)  # noqa: E712
            result = await db.execute(stmt)
            sources = list(result.scalars().all())

            updated = 0
            for source in sources:
                try:
                    await fetch_with_retry(
                        source.url, source_name=source.name, max_retries=1
                    )
                    source.consecutive_failures = 0
                    source.last_successful_fetch_at = utcnow()
                except Exception:
                    source.consecutive_failures += 1
                    if source.consecutive_failures >= 5:
                        source.is_active = False
                        logger.warning(
                            "source_disabled",
                            source=source.name,
                            failures=source.consecutive_failures,
                        )
                updated += 1

            await db.commit()

        logger.info(
            "job_completed",
            job="refresh_source_health",
            sources_checked=updated,
        )

    except Exception as exc:
        logger.error(
            "job_failed",
            job="refresh_source_health",
            error=str(exc),
            exc_info=True,
        )
