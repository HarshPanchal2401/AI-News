"""
AI Pulse – FCM Notification Service
=====================================
Firebase Cloud Messaging integration for push notifications.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotificationError
from app.core.logging import get_logger
from app.models import DailyBrief, Notification
from app.models.user import User

logger = get_logger(__name__)


def _initialize_firebase() -> None:
    """Initialize Firebase Admin SDK from credentials."""
    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            return  # Already initialized

        if settings.firebase_credentials_json:
            cred_dict = json.loads(settings.firebase_credentials_json)
            cred = credentials.Certificate(cred_dict)
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

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> str | None:
        """
        Send a push notification to a single device.

        Args:
            fcm_token: FCM registration token.
            title: Notification title.
            body: Notification body text.
            data: Additional data payload for deep linking.

        Returns:
            FCM message ID on success, None on failure.
        """
        try:
            from firebase_admin import messaging

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

            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: messaging.send(message),
            )
            return response

        except Exception as exc:
            logger.error(
                "fcm_send_failed",
                token=fcm_token[:20] + "...",
                error=str(exc),
            )
            return None

    async def send_batch(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict | None = None,
    ) -> dict[str, int]:
        """
        Send a notification to multiple devices (up to 500 per call).

        Returns:
            Stats dict: {success_count, failure_count}.
        """
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


class DailyNotificationSender:
    """
    Sends daily brief push notifications to all eligible users.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.fcm = FCMClient()

    async def send_all(self) -> dict[str, int]:
        """
        Send daily brief notifications to all users with:
        - notifications enabled
        - a daily brief generated for today
        - an FCM token registered

        Returns:
            Stats dict: {sent, skipped, failed}.
        """
        from app.utils.date_utils import today_utc, utcnow

        today = today_utc()

        # Get users who have today's brief and haven't been notified
        stmt = (
            select(User, DailyBrief)
            .join(DailyBrief, DailyBrief.user_id == User.id)
            .join(UserPreferences, UserPreferences.user_id == User.id, isouter=True)
            .where(
                User.is_active == True,  # noqa: E712
                User.fcm_token.is_not(None),
                DailyBrief.brief_date == today,
                DailyBrief.notification_sent == False,  # noqa: E712
            )
        )

        from app.models.user import UserPreferences

        stmt = (
            select(User, DailyBrief)
            .join(DailyBrief, DailyBrief.user_id == User.id)
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

        sent = 0
        skipped = 0
        failed = 0

        for user, brief in rows:
            try:
                title = "📰 Your AI Daily Brief is Ready"
                body = f"Today's top {brief.total_articles} AI stories — personalized for you."

                msg_id = await self.fcm.send_notification(
                    fcm_token=user.fcm_token,
                    title=title,
                    body=body,
                    data={
                        "type": "daily_brief",
                        "brief_id": str(brief.id),
                        "brief_date": str(brief.brief_date),
                        "article_count": str(brief.total_articles),
                    },
                )

                # Record the notification
                notification = Notification(
                    user_id=user.id,
                    title=title,
                    body=body,
                    notification_type="daily_brief",
                    data={"brief_id": str(brief.id)},
                    sent_at=utcnow(),
                    fcm_message_id=msg_id,
                    delivery_status="sent" if msg_id else "failed",
                )
                self.db.add(notification)

                # Mark brief as notified
                brief.notification_sent = True
                brief.sent_at = utcnow()

                if msg_id:
                    sent += 1
                else:
                    failed += 1

            except Exception as exc:
                logger.error(
                    "notification_send_error",
                    user_id=str(user.id),
                    error=str(exc),
                )
                failed += 1

        await self.db.commit()

        logger.info(
            "notifications_sent",
            total=len(rows),
            sent=sent,
            skipped=skipped,
            failed=failed,
        )
        return {"sent": sent, "skipped": skipped, "failed": failed}
