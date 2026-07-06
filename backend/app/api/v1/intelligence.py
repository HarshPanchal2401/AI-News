"""
AI News Intelligence Engine – Events, Trends, Digest & Search API
====================================================================
New API endpoints for the Intelligence Engine features:

  GET /events              — List NewsEvents (paginated, sorted by priority)
  GET /events/{id}         — Get single event with full detail
  GET /events/breaking     — Breaking events only (priority >= 95, age < 4h)
  GET /trends              — Current trending signals
  GET /trends/{type}       — Trending by type (company, topic, model, keyword)
  GET /digest              — Daily AI industry digest
  GET /search              — Semantic + keyword search
  POST /pipeline/trigger   — Manually trigger the intelligence pipeline (admin)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_optional_user
from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.models.trend import Trend
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence Engine"])


# ── Events API ────────────────────────────────────────────────────────────────

@router.get(
    "/events",
    summary="List AI news events",
    description="Paginated list of news events sorted by priority score.",
)
async def list_events(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category: Annotated[str | None, Query(description="Filter by category")] = None,
    event_type: Annotated[str | None, Query(description="Filter by event type")] = None,
    breaking_only: Annotated[bool, Query(description="Return breaking events only")] = False,
    min_priority: Annotated[float, Query(ge=0, le=100)] = 0.0,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List events with rich filtering options."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    conditions = [
        NewsEvent.published_at >= cutoff,
        NewsEvent.priority_score >= min_priority,
    ]
    if category:
        conditions.append(NewsEvent.category == category)
    if event_type:
        conditions.append(NewsEvent.event_type == event_type)
    if breaking_only:
        conditions.append(NewsEvent.is_breaking == True)  # noqa: E712

    # Count total
    from sqlalchemy import func, select as sa_select
    count_stmt = sa_select(func.count(NewsEvent.id)).where(and_(*conditions))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    stmt = (
        select(NewsEvent)
        .where(and_(*conditions))
        .order_by(desc(NewsEvent.priority_score), desc(NewsEvent.published_at))
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    return {
        "events": [_serialize_event(e) for e in events],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get(
    "/events/breaking",
    summary="Get breaking AI news events",
)
async def get_breaking_events(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return currently active breaking news events."""
    stmt = (
        select(NewsEvent)
        .where(NewsEvent.is_breaking == True)  # noqa: E712
        .order_by(desc(NewsEvent.priority_score), desc(NewsEvent.published_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    return {
        "breaking_events": [_serialize_event(e) for e in events],
        "count": len(events),
    }


@router.get(
    "/events/{event_id}",
    summary="Get a single event with full detail",
)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get full details of a single news event including all AI analysis."""
    from sqlalchemy.orm import selectinload
    stmt = select(NewsEvent).options(selectinload(NewsEvent.articles)).where(NewsEvent.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    return _serialize_event_full(event)


# ── Trends API ────────────────────────────────────────────────────────────────

@router.get(
    "/trends",
    summary="Get current AI trends",
)
async def get_trends(
    window_hours: Annotated[int, Query(description="Time window: 6, 24, or 168")] = 24,
    trend_type: Annotated[str | None, Query(description="company|topic|model|keyword|technology")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get trending topics, companies, models, and keywords."""
    if window_hours not in (6, 24, 168):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="window_hours must be 6, 24, or 168",
        )

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours + 12)

    conditions = [
        Trend.period_hours == window_hours,
        Trend.period_start >= cutoff,
    ]
    if trend_type:
        conditions.append(Trend.trend_type == trend_type)

    stmt = (
        select(Trend)
        .where(and_(*conditions))
        .order_by(desc(Trend.trend_score))
        .limit(limit)
    )
    result = await db.execute(stmt)
    trends = result.scalars().all()

    return {
        "trends": [_serialize_trend(t) for t in trends],
        "window_hours": window_hours,
        "trend_type": trend_type,
        "count": len(trends),
    }


@router.get(
    "/trends/companies",
    summary="Get trending AI companies",
)
async def get_trending_companies(
    window_hours: int = 24,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the top trending AI companies."""
    return await get_trends(
        window_hours=window_hours,
        trend_type="company",
        limit=limit,
        db=db,
    )


@router.get(
    "/trends/models",
    summary="Get trending AI models",
)
async def get_trending_models(
    window_hours: int = 24,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the top trending AI models."""
    return await get_trends(
        window_hours=window_hours,
        trend_type="model",
        limit=limit,
        db=db,
    )


# ── Digest API ────────────────────────────────────────────────────────────────

@router.get(
    "/digest",
    summary="Get the AI industry daily digest",
)
async def get_daily_digest(
    target_date: Annotated[str | None, Query(description="Date in YYYY-MM-DD format")] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get the full AI industry digest for a given date.
    Generates on-the-fly if not cached, then caches for 12 hours.
    """
    from app.services.digest_generator import DailyDigestGenerator

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid date format. Use YYYY-MM-DD.",
            )

    # Try Redis cache first
    cache_key = f"digest:{(parsed_date or datetime.now(timezone.utc).date()).isoformat()}"
    try:
        import json
        from app.services.cache.redis_client import get_redis_client
        redis = get_redis_client()
        if redis:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
    except Exception:
        pass

    generator = DailyDigestGenerator(db)
    digest = await generator.generate(target_date=parsed_date)

    # Cache it
    try:
        import json
        from app.services.cache.redis_client import get_redis_client
        redis = get_redis_client()
        if redis:
            await redis.set(cache_key, json.dumps(digest), ex=43200)  # 12h
    except Exception:
        pass

    return digest


@router.get(
    "/weekly-brief",
    summary="Get rolling AI industry Weekly Brief",
)
async def get_weekly_brief(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get a rolling 7-day executive brief.
    If the top 5 news events have changed, the AI-generated weekly summary is regenerated.
    """
    import hashlib
    import json
    from datetime import timedelta
    from app.services.ai.gemini_client import get_gemini_client
    from app.services.cache.redis_client import get_redis_client

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Fetch top 5 news events from last 7 days sorted by priority
    stmt = (
        select(NewsEvent)
        .where(NewsEvent.published_at >= cutoff)
        .order_by(desc(NewsEvent.priority_score))
        .limit(5)
    )
    result = await db.execute(stmt)
    top_events = list(result.scalars().all())

    if not top_events:
        return {
            "summary": "No major AI news events detected in the last 7 days.",
            "events": [],
            "hash_key": "",
        }

    # Generate a hash of these top events (ID + headline)
    hash_src = "".join(f"{e.id}:{e.headline}" for e in top_events)
    hash_key = hashlib.sha256(hash_src.encode("utf-8")).hexdigest()
    cache_key = f"weekly_brief:{hash_key}"

    # Try Redis cache first
    try:
        redis = get_redis_client()
        if redis:
            cached = await redis.get(cache_key)
            if cached:
                return {
                    "summary": cached,
                    "events": [_serialize_event(e) for e in top_events],
                    "hash_key": hash_key,
                    "cached": True,
                }
    except Exception as exc:
        logger.warning("weekly_brief_cache_error", error=str(exc))

    # Generate summary with Gemini
    headlines = "\n".join(
        f"- {e.headline} ({e.category}): {e.summary or ''}"
        for e in top_events
    )

    prompt = f"""You are a senior AI market research director. Write a professional, extremely concise rolling weekly brief (3-4 sentences) summarizing the major developments in the AI industry based on the top news events from the last 7 days:

{headlines}

Ensure the summary is cohesive, highlights key industry impacts, and explains the overarching trends of this week. Focus on quality, objectivity, and brevity."""

    try:
        client = get_gemini_client()
        summary = await client.generate_text(prompt)
    except Exception as exc:
        logger.error("weekly_brief_generation_error", error=str(exc))
        summary = "AI industry continues to evolve rapidly with significant model releases and market developments."

    # Cache the result in Redis
    try:
        redis = get_redis_client()
        if redis and summary:
            await redis.set(cache_key, summary, ex=86400)  # 24h cache
    except Exception as exc:
        logger.warning("weekly_brief_cache_write_error", error=str(exc))

    return {
        "summary": summary,
        "events": [_serialize_event(e) for e in top_events],
        "hash_key": hash_key,
        "cached": False,
    }



# ── Search API ────────────────────────────────────────────────────────────────

@router.get(
    "/search",
    summary="Semantic + keyword search over AI news events",
)
async def search_events(
    q: Annotated[str, Query(min_length=2, max_length=500, description="Search query")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    category: Annotated[str | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Search AI news events using semantic similarity + keyword matching.

    Supports natural language queries like:
    - "OpenAI latest announcements"
    - "AI funding this week"
    - "New Claude model"
    - "multimodal AI research"
    """
    from app.services.search_service import SearchService

    service = SearchService(db)
    results = await service.search(
        query=q,
        limit=limit,
        days=days,
        category=category,
        event_type=event_type,
    )

    return {
        "query": q,
        "results": results,
        "count": len(results),
        "days": days,
    }


# ── Admin Pipeline Trigger ─────────────────────────────────────────────────────

@router.post(
    "/pipeline/trigger",
    summary="Manually trigger the intelligence pipeline (admin)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_pipeline(
    run_ai: Annotated[bool, Query(description="Also run AI enrichment")] = True,
    run_trends: Annotated[bool, Query(description="Also run trending engine")] = False,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger the news intelligence pipeline."""
    import asyncio
    from app.scheduler.jobs import job_fetch_and_cluster_news, job_run_ai_enrichment, job_compute_trends

    # Run pipeline in background
    async def run():
        await job_fetch_and_cluster_news()
        if run_ai:
            await job_run_ai_enrichment()
        if run_trends:
            await job_compute_trends()

    asyncio.create_task(run())

    return {
        "status": "triggered",
        "message": "Intelligence pipeline started in background",
        "run_ai": run_ai,
        "run_trends": run_trends,
    }


# ── Serializers ───────────────────────────────────────────────────────────────

def _serialize_event(event: NewsEvent) -> dict[str, Any]:
    """Lightweight event serialization for list views."""
    return {
        "id": str(event.id),
        "headline": event.headline,
        "summary": event.summary,
        "category": event.category,
        "event_type": event.event_type,
        "priority_score": round(event.priority_score, 1),
        "freshness_score": round(event.freshness_score, 1),
        "trust_score": round(event.trust_score, 1),
        "trend_score": round(event.trend_score, 1),
        "is_breaking": event.is_breaking,
        "urgency": event.urgency,
        "sentiment": event.sentiment,
        "companies": event.companies[:5] if event.companies else [],
        "tags": event.tags[:5] if event.tags else [],
        "models_mentioned": event.models_mentioned[:3] if event.models_mentioned else [],
        "source_count": event.source_count,
        "source_domains": event.source_domains[:3] if event.source_domains else [],
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "primary_source_url": event.primary_source_url,
        "image_url": event.image_url,
        "funding_amount": event.funding_amount,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _serialize_event_full(event: NewsEvent) -> dict[str, Any]:
    """Full event serialization for detail view."""
    base = _serialize_event(event)
    articles_data = []
    if event.articles:
        for art in event.articles:
            articles_data.append({
                "id": str(art.id),
                "title": art.title,
                "url": art.url,
                "source_domain": art.source_domain,
                "description": art.description,
                "content_snippet": art.content_snippet,
                "published_at": art.published_at.isoformat() if art.published_at else None,
                "is_official": art.is_official_source,
                "trust_score": art.trust_score,
            })

    base.update({
        "executive_summary": event.executive_summary,
        "key_takeaways": event.key_takeaways or [],
        "subcategory": event.subcategory,
        "products_mentioned": event.products_mentioned or [],
        "people_mentioned": event.people_mentioned or [],
        "technologies_mentioned": event.technologies_mentioned or [],
        "programming_languages": event.programming_languages or [],
        "keywords": event.keywords or [],
        "companies": event.companies or [],
        "tags": event.tags or [],
        "funding_currency": event.funding_currency,
        "research_paper_url": event.research_paper_url,
        "arxiv_id": event.arxiv_id,
        "countries_affected": event.countries_affected or [],
        "industries_affected": event.industries_affected or [],
        "market_impact": event.market_impact,
        "business_opportunities": event.business_opportunities,
        "risks": event.risks,
        "confidence_score": event.confidence_score,
        "impact_score": round(event.impact_score, 1),
        "notification_sent": event.notification_sent,
        "source_domains": event.source_domains or [],
        "first_seen_at": event.first_seen_at.isoformat() if event.first_seen_at else None,
        "last_updated_at": event.last_updated_at.isoformat() if event.last_updated_at else None,
        "articles": articles_data,
    })
    return base


def _serialize_trend(trend: Trend) -> dict[str, Any]:
    """Trend serialization."""
    return {
        "id": str(trend.id),
        "trend_type": trend.trend_type,
        "name": trend.name,
        "slug": trend.slug,
        "trend_score": round(trend.trend_score, 1),
        "velocity": round(trend.velocity, 1),
        "mention_count": trend.mention_count,
        "source_count": trend.source_count,
        "event_count": trend.event_count,
        "is_emerging": trend.is_emerging,
        "top_headline": trend.top_headline,
        "period_hours": trend.period_hours,
        "period_start": trend.period_start.isoformat() if trend.period_start else None,
        "related_event_ids": trend.related_event_ids[:5] if trend.related_event_ids else [],
    }
