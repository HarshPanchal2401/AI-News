"""
AI Pulse – APScheduler Setup
==============================
Configures the AsyncIOScheduler for daily jobs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
    Configure and return the scheduler with all jobs registered.
    Does NOT start the scheduler — call scheduler.start() separately.
    """
    from app.scheduler.jobs import (
        job_cleanup_old_articles,
        job_fetch_and_process_news,
        job_send_notifications,
        job_refresh_source_health,
    )

    scheduler = get_scheduler()

    hour = settings.daily_brief_hour
    minute = settings.daily_brief_minute

    # ── Daily: Fetch + Process + Rank + Generate Briefs ──────────────────────
    scheduler.add_job(
        job_fetch_and_process_news,
        trigger=CronTrigger(
            hour=hour,
            minute=minute,
            timezone=settings.scheduler_timezone,
        ),
        id="daily_news_pipeline",
        name="Daily AI News Pipeline",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,  # 30 minutes grace period
    )

    # ── Daily: Send push notifications (5 min after pipeline) ────────────────
    notif_minute = (minute + 5) % 60
    notif_hour = hour + (1 if minute > 54 else 0)

    scheduler.add_job(
        job_send_notifications,
        trigger=CronTrigger(
            hour=notif_hour,
            minute=notif_minute,
            timezone=settings.scheduler_timezone,
        ),
        id="daily_notifications",
        name="Daily Push Notifications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    # ── Daily: Cleanup old articles (midnight UTC) ────────────────────────────
    scheduler.add_job(
        job_cleanup_old_articles,
        trigger=CronTrigger(
            hour=0,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="daily_cleanup",
        name="Daily Article Cleanup",
        replace_existing=True,
        max_instances=1,
    )

    # ── Every 6h: Refresh source health ──────────────────────────────────────
    scheduler.add_job(
        job_refresh_source_health,
        trigger=CronTrigger(
            hour="*/6",
            timezone=settings.scheduler_timezone,
        ),
        id="source_health_refresh",
        name="Source Health Refresh",
        replace_existing=True,
        max_instances=1,
    )

    logger.info(
        "scheduler_configured",
        job_count=len(scheduler.get_jobs()),
        daily_hour=hour,
        daily_minute=minute,
        timezone=settings.scheduler_timezone,
    )

    return scheduler
