"""
AI News Intelligence Engine – Scheduler Job Implementations
=============================================================
Async job functions executed by APScheduler.
Each job gets its own DB session and handles its own cleanup.

Jobs:
  - job_fetch_and_cluster_news (every 2h) — full intelligence pipeline
  - job_run_ai_enrichment (every 2h, after clustering) — Gemini analysis
  - job_refresh_freshness (every 2h) — update freshness scores
  - job_dispatch_breaking_news (every 2h) — send breaking news notifications
  - job_compute_trends (every 6h) — trending engine
  - job_generate_daily_digest (daily 10:00) — full digest
  - job_send_notifications (daily) — personalized briefs
  - job_cleanup_old_articles (daily midnight) — remove old content
  - job_refresh_source_health (every 6h) — source health monitoring
"""

from __future__ import annotations

import json
import uuid

from app.core.logging import get_logger
from app.utils.date_utils import days_ago, utcnow

logger = get_logger(__name__)


# ── Job 1: Fetch + Validate + Cluster ────────────────────────────────────────

async def job_fetch_and_cluster_news() -> None:
    """
    Core Intelligence Pipeline (runs every 2 hours):
    1. Fetch from all ~30 sources
    2. AI relevance + freshness validation
    3. Duplicate detection
    4. Save new articles to DB
    5. Event clustering (group same-story articles)
    6. Priority scoring for new events
    7. Dispatch breaking news notifications
    """
    logger.info("job_started", job="fetch_and_cluster_news")
    start = utcnow()

    from app.database.connection import AsyncSessionLocal
    from app.models.news_article import NewsArticle
    from app.services.duplicate_detection.engine import DuplicateDetectionEngine
    from app.services.event_clustering import EventClusteringEngine
    from app.services.news_fetchers.orchestrator import NewsFetchOrchestrator
    from app.services.notifications.notification_dispatcher import NotificationDispatcher
    from app.services.verification.engine import VerificationEngine
    from app.utils.text_utils import (
        content_fingerprint,
        normalize_title,
        normalize_url,
        title_fingerprint,
    )

    stats = {
        "fetched": 0,
        "pre_filtered": 0,
        "verified": 0,
        "duplicates": 0,
        "saved": 0,
        "events_created": 0,
        "events_updated": 0,
        "notifications_sent": 0,
    }

    try:
        # ── Step 1: Fetch ─────────────────────────────────────────────────────
        from sqlalchemy import select
        from app.models.news_source import NewsSource
        
        inactive_sources = set()
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(NewsSource.name).where(NewsSource.is_active == False))
                inactive_sources = set(result.scalars().all())
        except Exception as e:
            logger.warning("failed_to_load_inactive_sources_from_db", error=str(e))

        orchestrator = NewsFetchOrchestrator()
        raw_articles = await orchestrator.fetch_all(inactive_sources=inactive_sources)
        stats["fetched"] = len(raw_articles)

        # ── Step 2: Validate (AI relevance + freshness + content) ─────────────
        verification_engine = VerificationEngine()
        verified_pairs = verification_engine.verify_batch(raw_articles)
        stats["pre_filtered"] = len(raw_articles) - len(verified_pairs)
        stats["verified"] = sum(1 for _, r in verified_pairs if r.is_verified)

        trusted_pairs = [(raw, trust) for raw, trust in verified_pairs if trust.is_verified]

        async with AsyncSessionLocal() as db:
            # ── Step 3: Duplicate detection + save ────────────────────────────
            dup_engine = DuplicateDetectionEngine(db)
            saved_articles = []
            unique_raw_articles = []

            for raw, trust_result in trusted_pairs:
                dup_result = await dup_engine.check(raw)
                if dup_result.is_duplicate:
                    stats["duplicates"] += 1
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

                unique_raw_articles.append((raw, trust_result))

            # Generate embeddings and scrape full body text for unique articles
            if unique_raw_articles:
                from app.services.ai.gemini_client import get_gemini_client
                from app.utils.http_client import scrape_article_text
                import asyncio
                client = get_gemini_client()

                async def get_details(raw_item):
                    try:
                        emb_task = client.generate_embedding(raw_item.title)
                        scrap_task = scrape_article_text(raw_item.url)
                        emb, scraped_text = await asyncio.gather(emb_task, scrap_task)
                        return emb, scraped_text
                    except Exception as e:
                        logger.warning("fetch_details_error", url=raw_item.url, error=str(e))
                        return None, (raw_item.content_snippet or raw_item.description or "")

                details = await asyncio.gather(
                    *(get_details(raw) for raw, _ in unique_raw_articles)
                )

                for (raw, trust_result), (embedding, scraped_text) in zip(unique_raw_articles, details):
                    article = NewsArticle(
                        title=raw.title,
                        normalized_title=normalize_title(raw.title),
                        url=raw.url,
                        normalized_url=normalize_url(raw.url),
                        image_url=raw.image_url,
                        description=raw.description or (scraped_text[:200] + "..." if scraped_text else None),
                        content_snippet=scraped_text or raw.content_snippet,
                        author=raw.author,
                        published_at=raw.published_at,
                        source_domain=raw.source_domain,
                        title_fingerprint=title_fingerprint(raw.title),
                        content_fingerprint=content_fingerprint(raw.title, raw.content_snippet or ""),
                        embedding_json=json.dumps(embedding) if embedding else None,
                        is_duplicate=False,
                        is_verified=trust_result.is_verified,
                        trust_score=trust_result.trust_score,
                        verification_notes=trust_result.notes,
                        is_official_source=raw.is_official,
                        supporting_sources=[],
                    )
                    db.add(article)
                    saved_articles.append((article, raw))
                    stats["saved"] += 1

            await db.commit()
            logger.info("articles_saved", count=stats["saved"])

            # ── Step 4: Event Clustering ───────────────────────────────────────
            if unique_raw_articles:
                only_raw = [raw for raw, _ in unique_raw_articles]
                clustering_engine = EventClusteringEngine(db)
                events_created, events_updated = await clustering_engine.process_batch(only_raw)
                stats["events_created"] = events_created
                stats["events_updated"] = events_updated

            # ── Step 5: Dispatch breaking news notifications ───────────────────
            dispatcher = NotificationDispatcher(db)
            notif_stats = await dispatcher.dispatch_breaking_news()
            stats["notifications_sent"] = notif_stats["notifications_sent"]

        duration = (utcnow() - start).total_seconds()
        logger.info(
            "job_completed",
            job="fetch_and_cluster_news",
            duration_seconds=round(duration, 1),
            **stats,
        )

    except Exception as exc:
        logger.error(
            "job_failed",
            job="fetch_and_cluster_news",
            error=str(exc),
            exc_info=True,
        )


# ── Job 2: AI Enrichment ──────────────────────────────────────────────────────

async def job_run_ai_enrichment() -> None:
    """
    AI Enrichment Pipeline (runs every 2 hours, after clustering):
    Process unprocessed articles through Gemini (25-field analysis).
    Updates parent NewsEvents with extracted metadata + re-scores priority.
    """
    logger.info("job_started", job="ai_enrichment")

    try:
        from app.database.connection import AsyncSessionLocal
        from app.services.ai.analyzer import BatchArticleProcessor

        async with AsyncSessionLocal() as db:
            processor = BatchArticleProcessor(db)
            stats = await processor.process_unprocessed()

        logger.info("job_completed", job="ai_enrichment", **stats)

    except Exception as exc:
        logger.error("job_failed", job="ai_enrichment", error=str(exc), exc_info=True)


# ── Job 3: Freshness Refresh ──────────────────────────────────────────────────

async def job_refresh_freshness() -> None:
    """
    Update freshness scores for all recent events (runs every 2 hours).
    Also clears breaking status for events older than 4 hours.
    """
    logger.info("job_started", job="refresh_freshness")

    try:
        from app.database.connection import AsyncSessionLocal
        from app.services.freshness_engine import FreshnessEngine

        async with AsyncSessionLocal() as db:
            engine = FreshnessEngine(db)
            updated = await engine.refresh_all_events()
            cleared = await engine.mark_events_not_breaking()

        logger.info(
            "job_completed",
            job="refresh_freshness",
            events_updated=updated,
            breaking_cleared=cleared,
        )

    except Exception as exc:
        logger.error("job_failed", job="refresh_freshness", error=str(exc), exc_info=True)


# ── Job 4: Compute Trends ─────────────────────────────────────────────────────

async def job_compute_trends() -> None:
    """
    Compute trending signals for all time windows (runs every 6 hours).
    Generates Trend records for companies, topics, models, keywords, technologies.
    """
    logger.info("job_started", job="compute_trends")

    try:
        from app.database.connection import AsyncSessionLocal
        from app.services.trending_engine import TrendingEngine

        async with AsyncSessionLocal() as db:
            engine = TrendingEngine(db)
            stats = await engine.compute_trends()

        logger.info("job_completed", job="compute_trends", **stats)

    except Exception as exc:
        logger.error("job_failed", job="compute_trends", error=str(exc), exc_info=True)


# ── Job 5: Generate Daily Digest ──────────────────────────────────────────────

async def job_generate_daily_digest() -> None:
    """
    Generate the full AI industry digest for today (runs at 10:00 UTC daily).
    Also triggers personalized brief generation for all users.
    """
    logger.info("job_started", job="generate_daily_digest")

    try:
        from app.database.connection import AsyncSessionLocal
        from app.services.digest_generator import DailyDigestGenerator
        from app.services.ranking.ranker import ArticleRanker

        async with AsyncSessionLocal() as db:
            # Re-rank all today's articles first
            ranker = ArticleRanker(db)
            ranked = await ranker.rank_all_today()

            # Generate digest
            generator = DailyDigestGenerator(db)
            digest = await generator.generate()

            # Store digest in cache (Redis)
            try:
                import json as json_module
                from app.services.cache.redis_client import get_redis_client
                redis = get_redis_client()
                if redis:
                    from datetime import date
                    cache_key = f"digest:{date.today().isoformat()}"
                    await redis.set(cache_key, json_module.dumps(digest), ttl_seconds=86400)
                    logger.info("digest_cached", key=cache_key)
            except Exception as cache_err:
                logger.warning("digest_cache_error", error=str(cache_err))

            # Generate personalized briefs
            try:
                from app.services.personalization.engine import PersonalizationEngine
                personalization = PersonalizationEngine(db)
                brief_stats = await personalization.generate_briefs_for_all_users()
                logger.info("personalized_briefs_generated", **brief_stats)
            except Exception as brief_err:
                logger.warning("personalized_briefs_error", error=str(brief_err))

        logger.info(
            "job_completed",
            job="generate_daily_digest",
            ranked_articles=ranked,
            digest_events=digest.get("total_events", 0),
        )

    except Exception as exc:
        logger.error("job_failed", job="generate_daily_digest", error=str(exc), exc_info=True)


# ── Job 6: Send Daily Notifications ──────────────────────────────────────────

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
        logger.error("job_failed", job="send_notifications", error=str(exc), exc_info=True)


# ── Job 7: Cleanup Old Articles ───────────────────────────────────────────────

async def job_cleanup_old_articles() -> None:
    """Delete articles and events older than CLEANUP_DAYS_OLD days."""
    logger.info("job_started", job="cleanup_old_articles")

    try:
        from sqlalchemy import delete as sa_delete
        from app.database.connection import AsyncSessionLocal
        from app.models.news_article import NewsArticle
        from app.models.news_event import NewsEvent
        from app.core.config import settings

        cutoff = days_ago(settings.cleanup_days_old)

        async with AsyncSessionLocal() as db:
            # Delete old articles
            stmt = sa_delete(NewsArticle).where(NewsArticle.created_at < cutoff)
            result = await db.execute(stmt)
            deleted_articles = result.rowcount

            # Delete old events with no recent articles
            stmt2 = sa_delete(NewsEvent).where(NewsEvent.created_at < cutoff)
            result2 = await db.execute(stmt2)
            deleted_events = result2.rowcount

            await db.commit()

        logger.info(
            "job_completed",
            job="cleanup_old_articles",
            deleted_articles=deleted_articles,
            deleted_events=deleted_events,
            cutoff_days=settings.cleanup_days_old,
        )

    except Exception as exc:
        logger.error("job_failed", job="cleanup_old_articles", error=str(exc), exc_info=True)


# ── Job 8: Source Health Refresh ──────────────────────────────────────────────

async def job_refresh_source_health() -> None:
    """Test all active news sources and update their health status."""
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
                    await fetch_with_retry(source.url, source_name=source.name, max_retries=1)
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

        logger.info("job_completed", job="refresh_source_health", sources_checked=updated)

    except Exception as exc:
        logger.error("job_failed", job="refresh_source_health", error=str(exc), exc_info=True)


# ── Legacy Alias (backward compatibility) ─────────────────────────────────────
async def job_fetch_and_process_news() -> None:
    """Legacy alias — routes to the new intelligence pipeline."""
    await job_fetch_and_cluster_news()
