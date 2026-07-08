"""
AI Pulse - FCM Notification Service
===================================
Firebase Cloud Messaging integration for push notifications.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import DailyBrief, Notification
from app.models.user import User, UserPreferences

logger = get_logger(__name__)


def _initialize_firebase() -> None:
    """Initialize Firebase Admin SDK from credentials."""
    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            return

        if settings.firebase_credentials_json:
            cred = credentials.Certificate(json.loads(settings.firebase_credentials_json))
        elif settings.firebase_credentials_path:
            cred = credentials.Certificate(settings.firebase_credentials_path)
        else:
            logger.warning("firebase_credentials_not_configured")
            return

        firebase_admin.initialize_app(cred)
        logger.info("firebase_initialized")
    except Exception as exc:
        logger.error("firebase_initialization_failed", error=str(exc))


class FCMClient:
    """Firebase Cloud Messaging client for sending push notifications."""

    def __init__(self) -> None:
        _initialize_firebase()

    def is_available(self) -> bool:
        return bool(settings.firebase_credentials_json or settings.firebase_credentials_path)

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> str | None:
        """Send a push notification to a single device."""
        try:
            from firebase_admin import messaging
            import asyncio

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                token=fcm_token,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        icon="notification_icon",
                        color="#6366f1",
                        channel_id="ai_pulse_daily",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(title=title, body=body),
                            badge=1,
                            sound="default",
                        )
                    )
                ),
            )

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: messaging.send(message))
        except Exception as exc:
            logger.error("fcm_send_failed", token=fcm_token[:20] + "...", error=str(exc))
            return None

    async def send_batch(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict | None = None,
    ) -> dict[str, int]:
        """Send a notification to multiple devices, up to 500 per batch."""
        if not tokens:
            return {"success_count": 0, "failure_count": 0}

        try:
            from firebase_admin import messaging
            import asyncio

            messages = [
                messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={k: str(v) for k, v in (data or {}).items()},
                    token=token,
                )
                for token in tokens[:500]
            ]
            loop = asyncio.get_event_loop()
            batch_response = await loop.run_in_executor(
                None,
                lambda: messaging.send_each(messages),
            )
            return {
                "success_count": batch_response.success_count,
                "failure_count": batch_response.failure_count,
            }
        except Exception as exc:
            logger.error("fcm_batch_send_failed", error=str(exc))
            return {"success_count": 0, "failure_count": len(tokens)}

    async def send_to_topic(
        self,
        topic: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> bool:
        """Send a notification to an FCM topic."""
        if not self.is_available():
            logger.debug("fcm_not_configured_skipping_topic", topic=topic)
            return True
        try:
            from firebase_admin import messaging
            import asyncio

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                topic=topic,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        icon="notification_icon",
                        color="#6366f1",
                        channel_id="ai_pulse_breaking",
                    ),
                ),
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: messaging.send(message))
            return bool(response)
        except Exception as exc:
            logger.error("fcm_topic_send_failed", topic=topic, error=str(exc))
            return False


class DailyNotificationSender:
    """Sends daily brief push notifications to all eligible users."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.fcm = FCMClient()

    async def send_all(self) -> dict[str, int]:
        """
        Send daily brief notifications.

        Pattern selection is deterministic rotation per user/day:
        career_action, hype_filter, direct_tool_drop. Quiet hours use UTC until
        the schema stores an IANA timezone; converting with zoneinfo later will
        give correct timezone and DST behavior.
        """
        from app.utils.date_utils import today_utc, utcnow

        today = today_utc()
        stmt = (
            select(User, DailyBrief, UserPreferences)
            .join(DailyBrief, DailyBrief.user_id == User.id)
            .join(UserPreferences, UserPreferences.user_id == User.id, isouter=True)
            .where(
                User.is_active == True,  # noqa: E712
                User.fcm_token.is_not(None),
                DailyBrief.brief_date == today,
                DailyBrief.notification_sent == False,  # noqa: E712
            )
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        if not rows:
            logger.info("no_pending_notifications")
            return {"sent": 0, "skipped": 0, "failed": 0}

        sent = skipped = failed = 0
        for user, brief, preferences in rows:
            try:
                if preferences and not preferences.notification_enabled:
                    skipped += 1
                    continue
                if not self._should_send_now(preferences):
                    skipped += 1
                    continue

                pattern = self._notification_pattern(user, brief)
                title, body = self._build_daily_content(pattern, brief)

                msg_id = await self.fcm.send_notification(
                    fcm_token=user.fcm_token,
                    title=title,
                    body=body,
                    data={
                        "type": "daily_brief",
                        "pattern": pattern,
                        "brief_id": str(brief.id),
                        "brief_date": str(brief.brief_date),
                        "article_count": str(brief.total_articles),
                    },
                )

                self.db.add(Notification(
                    user_id=user.id,
                    title=title,
                    body=body,
                    notification_type="daily_brief",
                    data={"brief_id": str(brief.id), "pattern": pattern},
                    sent_at=utcnow(),
                    fcm_message_id=msg_id,
                    delivery_status="sent" if msg_id else "failed",
                ))

                brief.notification_sent = True
                brief.sent_at = utcnow()

                if msg_id:
                    sent += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error("notification_send_error", user_id=str(user.id), error=str(exc))
                failed += 1

        await self.db.commit()
        logger.info("notifications_sent", total=len(rows), sent=sent, skipped=skipped, failed=failed)
        return {"sent": sent, "skipped": skipped, "failed": failed}

    def _notification_pattern(self, user: User, brief: DailyBrief) -> str:
        patterns = ["career_action", "hype_filter", "direct_tool_drop"]
        seed = f"{user.id}:{brief.brief_date.isoformat()}".encode("utf-8")
        return patterns[int(hashlib.sha256(seed).hexdigest(), 16) % len(patterns)]

    def _build_daily_content(self, pattern: str, brief: DailyBrief) -> tuple[str, str]:
        if pattern == "career_action":
            return (
                "Your AI Career Brief",
                f"{brief.total_articles} high-signal stories with one concrete next step.",
            )
        if pattern == "hype_filter":
            return (
                "Today's AI Signal",
                f"{brief.total_articles} items cleared the quality bar. No filler.",
            )
        return (
            "New Tools Worth Checking",
            f"{brief.total_articles} personalized AI updates are ready.",
        )

    def _should_send_now(self, preferences: UserPreferences | None) -> bool:
        if not preferences:
            return True
        hour = datetime.now(timezone.utc).hour
        quiet_start = settings.notification_quiet_hours_start
        quiet_end = settings.notification_quiet_hours_end
        if quiet_start <= quiet_end:
            return not (quiet_start <= hour < quiet_end)
        return not (hour >= quiet_start or hour < quiet_end)
