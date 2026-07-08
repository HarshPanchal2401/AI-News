"""
AI News Intelligence Engine – Breaking News Notification Dispatcher
=====================================================================
Dispatches real-time notifications for high-priority events.

Triggers when:
  - Priority Score ≥ configurable threshold (default: 80)
  - is_breaking = True
  - notification_sent = False

Notification templates:
  🚨 Breaking AI News: {headline}
  🤖 New Model Released: {headline}
  📈 NVIDIA/Hardware: {headline}
  💰 Funding: {headline}
  🚀 Product Launch: {headline}
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.models.news_article import NewsArticle
from app.models.user import User, UserPreferences
from app.services.priority_engine import PriorityEngine

logger = get_logger(__name__)

# Default priority threshold for notifications
DEFAULT_NOTIFICATION_THRESHOLD = settings.breaking_interrupt_threshold

INTERRUPT_EVENT_TYPES = {
    "model_release",
    "product_launch",
    "api_release",
    "security_incident",
    "government_regulation",
    "open_source_release",
    "infrastructure",
    "gpu",
}


class NotificationDispatcher:
    """
    Dispatches breaking news notifications for high-priority events.

    Called after event clustering and priority scoring.
    Only sends notifications for events that haven't been notified yet.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.priority_engine = PriorityEngine()
        self._threshold = DEFAULT_NOTIFICATION_THRESHOLD

    async def dispatch_breaking_news(
        self,
        threshold: float | None = None,
    ) -> dict[str, int]:
        """
        Find and dispatch notifications for all high-priority, unnotified events.

        Args:
            threshold: Priority threshold (default: settings value or 80.0).

        Returns:
            Stats: {events_found, notifications_sent, errors}
        """
        effective_threshold = threshold or settings.breaking_interrupt_threshold

        # Find unnotified high-priority events
        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.priority_score >= effective_threshold,
                NewsEvent.notification_sent == False,  # noqa: E712
            )
            .order_by(NewsEvent.priority_score.desc())
            .limit(20)  # Cap per run to avoid spam
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()

        if not events:
            logger.info("no_breaking_news_to_notify")
            return {"events_found": 0, "notifications_sent": 0, "errors": 0}

        stats = {"events_found": len(events), "notifications_sent": 0, "errors": 0}

        for event in events:
            try:
                if not self.is_interrupt_worthy(event, effective_threshold):
                    logger.info(
                        "breaking_candidate_deferred",
                        event_id=str(event.id),
                        event_type=event.event_type,
                        priority=event.priority_score,
                    )
                    continue
                sent = await self._dispatch_event_notification(event)
                if sent:
                    await self._update_personalized_brief_caches(event)
                    event.notification_sent = True
                    event.notification_sent_at = datetime.now(timezone.utc)
                    stats["notifications_sent"] += 1
            except Exception as exc:
                logger.error(
                    "notification_dispatch_error",
                    event_id=str(event.id),
                    error=str(exc),
                )
                stats["errors"] += 1

        try:
            await self.db.commit()
        except Exception as exc:
            logger.error("notification_dispatch_commit_error", error=str(exc))
            await self.db.rollback()

        logger.info(
            "breaking_news_dispatch_complete",
            events_found=stats["events_found"],
            notifications_sent=stats["notifications_sent"],
            errors=stats["errors"],
        )
        return stats

    def is_interrupt_worthy(self, event: NewsEvent, threshold: float | None = None) -> bool:
        """
        Breaking interrupt criteria.

        Qualifies immediately when base priority crosses the configured
        threshold and the story is a frontier model/product/API launch, a
        critical security or regulation event, a major outage/infrastructure
        item, or an exceptionally high-priority global story.
        """
        effective_threshold = threshold or settings.breaking_interrupt_threshold
        if event.priority_score < effective_threshold:
            return False
        if event.priority_score >= 95.0:
            return True
        return (event.event_type or "") in INTERRUPT_EVENT_TYPES

    async def _update_personalized_brief_caches(self, event: NewsEvent) -> None:
        """Merge interrupt delta articles into affected users' cached daily briefs."""
        if not self.is_interrupt_worthy(event):
            return

        article_result = await self.db.execute(
            select(NewsArticle)
            .options(selectinload(NewsArticle.analysis))
            .where(NewsArticle.event_id == event.id)
            .limit(10)
        )
        delta_articles = list(article_result.scalars().all())
        if not delta_articles:
            return

        user_result = await self.db.execute(
            select(User, UserPreferences)
            .join(UserPreferences, UserPreferences.user_id == User.id, isouter=True)
            .where(User.is_active == True)  # noqa: E712
            .limit(1000)
        )

        from app.services.personalization.engine import PersonalizationEngine
        personalization = PersonalizationEngine(self.db)

        affected = 0
        event_terms = {
            (event.category or "").lower(),
            (event.event_type or "").lower(),
            *(t.lower() for t in (event.tags or [])),
            *(c.lower() for c in (event.companies or [])),
            *(m.lower() for m in (event.models_mentioned or [])),
        }
        for user, prefs in user_result.all():
            if event.priority_score < 95.0 and prefs:
                pref_terms = {
                    *(t.lower() for t in (prefs.favorite_categories or [])),
                    *(t.lower() for t in (prefs.favorite_topics or [])),
                    *(t.lower() for t in (prefs.favorite_companies or [])),
                }
                if pref_terms and not (pref_terms & event_terms):
                    continue
            await personalization.incorporate_breaking_delta(user.id, delta_articles)
            affected += 1

        logger.info(
            "breaking_delta_briefs_updated",
            event_id=str(event.id),
            affected_users=affected,
            delta_articles=len(delta_articles),
        )

    async def _dispatch_event_notification(self, event: NewsEvent) -> bool:
        """
        Build and send a notification for a single event.

        Returns True if sent successfully.
        """
        title, body = self._build_notification_content(event)

        logger.info(
            "dispatching_breaking_notification",
            event_id=str(event.id),
            headline=event.headline[:80],
            priority=event.priority_score,
            title=title,
        )

        # Try Firebase FCM (mobile push)
        fcm_sent = await self._send_fcm(title, body, event)

        return fcm_sent

    def _build_notification_content(
        self, event: NewsEvent
    ) -> tuple[str, str]:
        """
        Build notification title and body based on event type and priority.
        """
        emoji = self.priority_engine.get_notification_emoji(
            event.event_type,
            list(event.companies or []),
        )

        # Priority tier label
        tier_label = self.priority_engine.get_tier_label(event.priority_score)

        # Smart title
        if event.priority_score >= 95:
            prefix = "🚨 Breaking AI News"
        elif event.event_type == "model_release":
            company = event.companies[0] if event.companies else "AI"
            prefix = f"🤖 New {company} Model"
        elif event.event_type == "funding":
            amount = f"${event.funding_amount:.0f}M" if event.funding_amount else ""
            prefix = f"💰 AI Funding{' ' + amount if amount else ''}"
        elif event.event_type == "product_launch":
            prefix = "🚀 Product Launch"
        elif event.event_type in ("gpu", "infrastructure"):
            prefix = "📈 AI Hardware"
        elif event.event_type == "government_regulation":
            prefix = "⚖️ AI Regulation"
        elif event.event_type == "acquisition":
            prefix = "🤝 AI Acquisition"
        elif event.event_type == "research_paper":
            prefix = "📄 AI Research"
        elif event.event_type == "security_incident":
            prefix = "⚠️ AI Security"
        else:
            prefix = f"{emoji} AI News"

        title = prefix
        body = event.headline[:200]

        if event.summary and len(event.summary) > 20:
            body = f"{event.headline[:120]}. {event.summary[:100]}"

        return title, body

    async def _send_fcm(
        self, title: str, body: str, event: NewsEvent
    ) -> bool:
        """
        Send a Firebase Cloud Messaging notification to all users.
        Falls back gracefully if Firebase is not configured.
        """
        try:
            from app.services.notifications.fcm_client import FCMClient
            fcm = FCMClient()

            if not fcm.is_available():
                logger.debug("fcm_not_configured_skipping")
                return True  # Not an error — just not configured

            notification_data = {
                "event_id": str(event.id),
                "event_type": event.event_type or "news",
                "priority": str(int(event.priority_score)),
                "category": event.category,
                "url": event.primary_source_url or "",
            }

            # Send to topic (all users) for breaking news
            success = await fcm.send_to_topic(
                topic="breaking_ai_news",
                title=title,
                body=body,
                data=notification_data,
            )
            return success

        except ImportError:
            logger.warning("fcm_client_not_available")
            return False
        except Exception as exc:
            logger.error("fcm_send_error", error=str(exc))
            return False
