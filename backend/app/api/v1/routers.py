"""
AI Pulse – Remaining API Routers
==================================
Users, Preferences, Brief, Bookmarks, Notifications, Categories, Health, Admin.
"""

from __future__ import annotations

import math
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin, get_current_user
from app.core.exceptions import DuplicateError, NotFoundError
from app.database.connection import check_database_connection, get_db
from app.models import Bookmark, Category, DailyBrief, Notification
from app.models.news_article import NewsArticle
from app.models.news_analysis import NewsAnalysis
from app.models.news_source import NewsSource
from app.models.user import User, UserPreferences
from app.schemas import (
    AdminStatsResponse,
    BookmarkCreateRequest,
    BookmarkResponse,
    CategoryResponse,
    DailyBriefResponse,
    DailyBriefSummary,
    DetailedHealthResponse,
    FCMTokenRequest,
    HealthResponse,
    NewsArticleListResponse,
    NewsSourceAdminResponse,
    NewsSourceUpdateRequest,
    NotificationResponse,
    PreferencesResponse,
    PreferencesUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.core.config import settings
from app.utils.date_utils import today_utc, utcnow


# ── Users Router ──────────────────────────────────────────────────────────────

users_router = APIRouter(prefix="/users", tags=["Users"])


@users_router.get("/me", response_model=UserResponse, summary="Get current user profile")
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@users_router.put("/me", response_model=UserResponse, summary="Update user profile")
async def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url
    current_user.last_seen_at = utcnow()
    try:
        from app.services.personalization.engine import PersonalizationEngine
        engine = PersonalizationEngine(db)
        await engine.regenerate_after_profile_change(current_user.id)
    except Exception:
        pass
    await db.commit()
    await db.refresh(current_user)
    return current_user


@users_router.post("/me/fcm-token", status_code=status.HTTP_200_OK, summary="Register FCM device token")
async def register_fcm_token(
    payload: FCMTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    current_user.fcm_token = payload.fcm_token
    await db.commit()
    return {"status": "ok"}


# ── Preferences Router ────────────────────────────────────────────────────────

preferences_router = APIRouter(prefix="/preferences", tags=["Preferences"])


@preferences_router.get("", response_model=PreferencesResponse, summary="Get user preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferences:
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = UserPreferences(user_id=current_user.id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs


@preferences_router.put("", response_model=PreferencesResponse, summary="Update user preferences")
async def update_preferences(
    payload: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferences:
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = UserPreferences(user_id=current_user.id)
        db.add(prefs)

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(prefs, field, value)

    try:
        from app.services.personalization.engine import PersonalizationEngine
        engine = PersonalizationEngine(db)
        await engine.regenerate_after_profile_change(current_user.id)
    except Exception:
        from app.services.cache.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.delete(f"brief:today:{current_user.id}")

    await db.commit()
    await db.refresh(prefs)
    return prefs


@preferences_router.get("/companies", summary="Get list of available companies")
async def get_available_companies() -> dict:
    from app.schemas import VALID_COMPANIES
    return {"companies": VALID_COMPANIES}


@preferences_router.get("/categories", summary="Get list of available categories")
async def get_available_categories() -> dict:
    from app.schemas import VALID_CATEGORIES
    return {"categories": VALID_CATEGORIES}


# ── Daily Brief Router ────────────────────────────────────────────────────────

brief_router = APIRouter(prefix="/brief", tags=["Daily Brief"])


@brief_router.get("/today", response_model=DailyBriefResponse, summary="Get today's personalized brief")
async def get_today_brief(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyBriefResponse:
    """
    Returns today's personalized AI news brief.
    Articles are ordered by personalized score.
    """
    from app.services.cache.redis_client import get_redis_client

    redis = get_redis_client()
    cache_key = f"brief:today:{current_user.id}"
    cached = await redis.get(cache_key)
    if cached:
        return DailyBriefResponse(**cached)

    today = today_utc()
    stmt = select(DailyBrief).where(
        DailyBrief.user_id == current_user.id,
        DailyBrief.brief_date == today,
    )
    result = await db.execute(stmt)
    brief = result.scalar_one_or_none()

    if not brief:
        # Generate on-demand if not yet created
        from app.services.personalization.engine import PersonalizationEngine
        engine = PersonalizationEngine(db)
        brief = await engine.generate_brief_for_user(current_user.id)
        if not brief:
            raise NotFoundError("Daily brief")

    # Fetch articles for the brief
    from app.api.v1.news import _article_to_list_schema

    article_ids = [uuid.UUID(str(aid)) for aid in brief.article_ids]
    articles_stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(NewsArticle.id.in_(article_ids))
    )
    articles_result = await db.execute(articles_stmt)
    articles_map = {str(a.id): a for a in articles_result.scalars().all()}

    # Preserve order from brief
    ordered_articles = [
        _article_to_list_schema(articles_map[aid])
        for aid in [str(i) for i in brief.article_ids]
        if str(aid) in articles_map
    ]

    response = DailyBriefResponse(
        id=brief.id,
        brief_date=brief.brief_date,
        total_articles=brief.total_articles,
        personalization_score=brief.personalization_score,
        sent_at=brief.sent_at,
        articles=ordered_articles,
        created_at=brief.created_at,
    )

    await redis.set(cache_key, response.model_dump(), ttl_seconds=settings.cache_ttl_brief)
    return response


@brief_router.get("/history", response_model=list[DailyBriefSummary], summary="Get brief history")
async def get_brief_history(
    limit: int = Query(default=30, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DailyBriefSummary]:
    stmt = (
        select(DailyBrief)
        .where(DailyBrief.user_id == current_user.id)
        .order_by(DailyBrief.brief_date.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── Bookmarks Router ──────────────────────────────────────────────────────────

bookmarks_router = APIRouter(prefix="/bookmarks", tags=["Bookmarks"])


@bookmarks_router.get("", response_model=list[BookmarkResponse], summary="Get user bookmarks")
async def get_bookmarks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Bookmark]:
    stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.article).selectinload(NewsArticle.analysis))
        .where(Bookmark.user_id == current_user.id)
        .order_by(Bookmark.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@bookmarks_router.post("", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED, summary="Bookmark an article")
async def create_bookmark(
    payload: BookmarkCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Bookmark:
    # Check article exists
    article_result = await db.execute(
        select(NewsArticle).where(NewsArticle.id == payload.article_id)
    )
    article = article_result.scalar_one_or_none()
    if not article:
        raise NotFoundError("Article", payload.article_id)

    # Check duplicate
    existing = await db.execute(
        select(Bookmark).where(
            Bookmark.user_id == current_user.id,
            Bookmark.article_id == payload.article_id,
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateError("Article is already bookmarked.")

    bookmark = Bookmark(
        user_id=current_user.id,
        article_id=payload.article_id,
        note=payload.note,
    )
    db.add(bookmark)
    article.bookmark_count += 1
    await db.commit()
    await db.refresh(bookmark)
    return bookmark


@bookmarks_router.delete("/{article_id}", status_code=status.HTTP_200_OK, summary="Remove bookmark")
async def delete_bookmark(
    article_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Bookmark).where(
            Bookmark.user_id == current_user.id,
            Bookmark.article_id == article_id,
        )
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        raise NotFoundError("Bookmark")

    # Decrement bookmark count
    article_result = await db.execute(select(NewsArticle).where(NewsArticle.id == article_id))
    article = article_result.scalar_one_or_none()
    if article and article.bookmark_count > 0:
        article.bookmark_count -= 1

    await db.delete(bookmark)
    await db.commit()
    return {"status": "deleted"}


# ── Notifications Router ──────────────────────────────────────────────────────

notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])


@notifications_router.get("", response_model=list[NotificationResponse], summary="Get notification history")
async def get_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@notifications_router.put("/{notification_id}/read", status_code=status.HTTP_200_OK, summary="Mark notification as read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise NotFoundError("Notification")

    notification.is_read = True
    notification.read_at = utcnow()
    await db.commit()
    return {"status": "read"}


@notifications_router.put("/read-all", status_code=status.HTTP_200_OK, summary="Mark all notifications as read")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import update
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True, read_at=utcnow())
    )
    await db.commit()
    return {"status": "all_read"}


# ── Categories Router ─────────────────────────────────────────────────────────

categories_router = APIRouter(prefix="/categories", tags=["Categories"])


@categories_router.get("", response_model=list[CategoryResponse], summary="List all categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[Category]:
    from app.services.cache.redis_client import get_redis_client
    redis = get_redis_client()
    cached = await redis.get("categories:all")
    if cached:
        return [CategoryResponse(**c) for c in cached]

    stmt = select(Category).where(Category.is_active == True).order_by(Category.display_order)  # noqa: E712
    result = await db.execute(stmt)
    categories = list(result.scalars().all())

    data = [CategoryResponse.model_validate(c).model_dump() for c in categories]
    await redis.set("categories:all", data, ttl_seconds=settings.cache_ttl_categories)
    return categories


# ── Health Router ─────────────────────────────────────────────────────────────

health_router = APIRouter(tags=["Health"])


@health_router.get("/health", response_model=HealthResponse, summary="Basic health check")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.app_env,
    )


@health_router.get("/health/detailed", response_model=DetailedHealthResponse, summary="Detailed health check")
async def health_detailed() -> DetailedHealthResponse:
    from app.services.cache.redis_client import get_redis_client
    from app.scheduler.scheduler import get_scheduler

    db_ok = await check_database_connection()
    redis = get_redis_client()
    cache_ok = await redis.ping()

    try:
        scheduler = get_scheduler()
        scheduler_ok = scheduler.running
    except Exception:
        scheduler_ok = False

    overall_status = "ok" if (db_ok and cache_ok) else "degraded"

    return DetailedHealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.app_env,
        database="ok" if db_ok else "error",
        cache="ok" if cache_ok else "error",
        scheduler="running" if scheduler_ok else "stopped",
        checks={
            "database": db_ok,
            "cache": cache_ok,
            "scheduler": scheduler_ok,
        },
    )


# ── Admin Router ──────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/admin", tags=["Admin"])


@admin_router.post("/fetch-now", summary="Manually trigger news fetch pipeline", status_code=status.HTTP_202_ACCEPTED)
async def trigger_fetch(
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_admin),
) -> dict:
    """Manually triggers the full news pipeline (runs in background)."""
    from app.scheduler.jobs import job_fetch_and_process_news
    background_tasks.add_task(job_fetch_and_process_news)
    return {"message": "News pipeline started in background.", "status": "accepted"}


@admin_router.get("/sources", response_model=list[NewsSourceAdminResponse], summary="List all news sources")
async def list_sources(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[NewsSource]:
    result = await db.execute(select(NewsSource).order_by(NewsSource.name))
    return list(result.scalars().all())


@admin_router.put("/sources/{source_id}", response_model=NewsSourceAdminResponse, summary="Update news source")
async def update_source(
    source_id: uuid.UUID,
    payload: NewsSourceUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> NewsSource:
    result = await db.execute(select(NewsSource).where(NewsSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise NotFoundError("NewsSource", source_id)

    if payload.is_active is not None:
        source.is_active = payload.is_active
    if payload.reliability_score is not None:
        source.reliability_score = payload.reliability_score

    await db.commit()
    await db.refresh(source)
    return source


@admin_router.get("/stats", response_model=AdminStatsResponse, summary="Get application stats")
async def get_stats(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminStatsResponse:
    from app.utils.date_utils import start_of_day

    today_start = start_of_day()

    total_articles = (await db.execute(select(func.count(NewsArticle.id)))).scalar_one()
    articles_today = (await db.execute(
        select(func.count(NewsArticle.id)).where(NewsArticle.created_at >= today_start)
    )).scalar_one()
    verified = (await db.execute(
        select(func.count(NewsArticle.id)).where(NewsArticle.is_verified == True)  # noqa: E712
    )).scalar_one()
    duplicates = (await db.execute(
        select(func.count(NewsArticle.id)).where(NewsArticle.is_duplicate == True)  # noqa: E712
    )).scalar_one()
    ai_processed = (await db.execute(
        select(func.count(NewsArticle.id)).where(NewsArticle.ai_processed == True)  # noqa: E712
    )).scalar_one()
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
    )).scalar_one()
    briefs_sent = (await db.execute(
        select(func.count(DailyBrief.id)).where(DailyBrief.notification_sent == True)  # noqa: E712
    )).scalar_one()
    sources_active = (await db.execute(
        select(func.count(NewsSource.id)).where(NewsSource.is_active == True)  # noqa: E712
    )).scalar_one()
    sources_failed = (await db.execute(
        select(func.count(NewsSource.id)).where(NewsSource.consecutive_failures >= 5)
    )).scalar_one()

    return AdminStatsResponse(
        total_articles=total_articles,
        articles_today=articles_today,
        verified_articles=verified,
        duplicate_articles=duplicates,
        ai_processed=ai_processed,
        total_users=total_users,
        active_users=active_users,
        total_briefs_sent=briefs_sent,
        sources_active=sources_active,
        sources_failed=sources_failed,
    )
