"""
AI News Intelligence Engine – APScheduler Setup
=================================================
Configures the AsyncIOScheduler for continuous AI news intelligence.

Schedule:
  Every 2h   : Fetch + cluster + breaking news dispatch
  Every 2h   : AI enrichment (Gemini 25-field analysis)
  Every 2h   : Freshness score refresh
  Every 6h   : Trending engine computation
  Daily 10:00: Generate daily digest + personalized briefs
  Daily 10:05: Send daily push notifications
  Daily 00:00: Cleanup old articles and events
  Every 6h   : Source health refresh
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Singleton scheduler instance
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the singleton scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone,
        )
    return _scheduler


def setup_scheduler() -> AsyncIOScheduler:
    """
    Configure and return the scheduler with all intelligence pipeline jobs.
    Does NOT start the scheduler — call scheduler.start() separately.
    """
    from app.scheduler.jobs import (
        job_cleanup_old_articles,
        job_compute_trends,
        job_fetch_and_cluster_news,
        job_generate_daily_digest,
        job_refresh_freshness,
        job_refresh_source_health,
        job_run_ai_enrichment,
        job_send_notifications,
    )

    scheduler = get_scheduler()
    tz = settings.scheduler_timezone

    # ── Every 2h: Fetch + Cluster + Breaking News ─────────────────────────────
    scheduler.add_job(
        job_fetch_and_cluster_news,
        trigger=IntervalTrigger(hours=2, timezone=tz),
        id="fetch_and_cluster_news",
        name="Fetch + Validate + Cluster into Events",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # ── Every 2h: AI Enrichment (offset by 30min from fetch) ─────────────────
    scheduler.add_job(
        job_run_ai_enrichment,
        trigger=IntervalTrigger(hours=2, start_date="2026-01-01 00:30:00", timezone=tz),
        id="ai_enrichment",
        name="AI Enrichment (Gemini 25-field analysis)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # ── Every 2h: Freshness Refresh (offset by 45min) ─────────────────────────
    scheduler.add_job(
        job_refresh_freshness,
        trigger=IntervalTrigger(hours=2, start_date="2026-01-01 00:45:00", timezone=tz),
        id="refresh_freshness",
        name="Freshness Score Refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    # ── Every 6h: Trending Engine ─────────────────────────────────────────────
    scheduler.add_job(
        job_compute_trends,
        trigger=CronTrigger(hour="*/6", minute=15, timezone=tz),
        id="compute_trends",
        name="Trending Engine (Companies, Topics, Models, Keywords)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=900,
    )

    # ── Daily: Generate Full Digest + Personalized Briefs ─────────────────────
    digest_hour = settings.daily_brief_hour
    digest_minute = settings.daily_brief_minute

    scheduler.add_job(
        job_generate_daily_digest,
        trigger=CronTrigger(
            hour=digest_hour,
            minute=digest_minute,
            timezone=tz,
        ),
        id="generate_daily_digest",
        name="Daily Digest + Personalized Briefs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # ── Daily: Send Push Notifications (5 min after digest) ───────────────────
    notif_minute = (digest_minute + 5) % 60
    notif_hour = digest_hour + (1 if digest_minute > 54 else 0)

    scheduler.add_job(
        job_send_notifications,
        trigger=CronTrigger(
            hour=notif_hour,
            minute=notif_minute,
            timezone=tz,
        ),
        id="send_notifications",
        name="Daily Push Notifications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    # ── Daily Midnight: Cleanup Old Articles + Events ─────────────────────────
    scheduler.add_job(
        job_cleanup_old_articles,
        trigger=CronTrigger(hour=0, minute=30, timezone=tz),
        id="daily_cleanup",
        name="Daily Article + Event Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # ── Every 6h: Source Health Refresh ───────────────────────────────────────
    scheduler.add_job(
        job_refresh_source_health,
        trigger=CronTrigger(hour="*/6", minute=45, timezone=tz),
        id="source_health_refresh",
        name="Source Health Refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "scheduler_configured",
        job_count=len(scheduler.get_jobs()),
        fetch_interval_hours=2,
        daily_digest_hour=digest_hour,
        timezone=tz,
    )

    return scheduler
