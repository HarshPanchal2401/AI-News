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

from sqlalchemy.orm import selectinload
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


# ── Suggestions API ───────────────────────────────────────────────────────────

from app.api.dependencies import get_current_user
from app.models.user import UserPreferences
from app.models import DailyBrief, Bookmark
from app.models.news_article import NewsArticle

@router.get(
    "/suggestions",
    summary="Get AI-powered career mentorship and market recommendations",
)
async def get_suggestions(
    suggestion_type: str = Query(default="personalized", description="personalized | market"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Returns AI-generated career mentor or market growth suggestions.
    Uses current news, daily briefs, and user telemetry as context.
    """
    import json
    from app.services.cache.redis_client import get_redis_client
    from app.services.ai.gemini_client import get_gemini_client
    from app.utils.date_utils import today_utc

    if suggestion_type not in ("personalized", "market"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="suggestion_type must be 'personalized' or 'market'",
        )

    # Cache check
    redis = get_redis_client()
    cache_key = f"suggestions:{suggestion_type}:{current_user.id}"
    try:
        if redis:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
    except Exception as exc:
        logger.warning("suggestions_cache_read_error", error=str(exc))

    # 1. Fetch user preferences
    prefs_stmt = select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    prefs_result = await db.execute(prefs_stmt)
    prefs = prefs_result.scalar_one_or_none()

    # 2. Fetch user bookmarks
    bookmarks_stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.article))
        .where(Bookmark.user_id == current_user.id)
        .limit(10)
    )
    bookmarks_result = await db.execute(bookmarks_stmt)
    bookmarks = list(bookmarks_result.scalars().all())

    # 3. Fetch today's daily brief
    today = today_utc()
    brief_stmt = select(DailyBrief).where(
        DailyBrief.user_id == current_user.id,
        DailyBrief.brief_date == today,
    )
    brief_result = await db.execute(brief_stmt)
    brief = brief_result.scalar_one_or_none()
    
    brief_article_titles = []
    if brief and brief.article_ids:
        brief_article_ids = [uuid.UUID(str(aid)) for aid in brief.article_ids]
        brief_arts_stmt = select(NewsArticle).where(NewsArticle.id.in_(brief_article_ids))
        brief_arts_res = await db.execute(brief_arts_stmt)
        brief_article_titles = [a.title for a in brief_arts_res.scalars().all()]

    # 4. Fetch recent top news articles (context of news)
    recent_stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(NewsArticle.is_verified == True, NewsArticle.is_duplicate == False)
        .order_by(desc(NewsArticle.final_score), desc(NewsArticle.created_at))
        .limit(15)
    )
    recent_result = await db.execute(recent_stmt)
    recent_articles = list(recent_result.scalars().all())

    recent_news_context = [
        {
            "title": art.title,
            "category": art.analysis.category if art.analysis else "General",
            "summary": art.analysis.summary if art.analysis else art.description,
            "companies": art.analysis.companies if art.analysis else [],
            "keywords": art.analysis.keywords if art.analysis else []
        }
        for art in recent_articles
    ]

    # Generate prompt
    user_name = current_user.display_name or "Developer"
    if suggestion_type == "personalized":
        user_profile = {
            "name": user_name,
            "favorite_categories": prefs.favorite_categories if prefs else [],
            "favorite_companies": prefs.favorite_companies if prefs else [],
            "favorite_topics": prefs.favorite_topics if prefs else [],
            "bookmarked_articles": [b.article.title for b in bookmarks if b.article],
            "today_brief_articles": brief_article_titles
        }

        prompt = f"""You are a senior AI career mentor and technical strategist.
Analyze the user's profile and behavioral context (bookmarks/preferences) along with the latest news to construct exactly 3 personalized recommendations.

User Profile Context:
{json.dumps(user_profile, indent=2)}

Latest AI News & Advancements:
{json.dumps(recent_news_context[:10], indent=2)}

You MUST formulate each recommendation to start with a mentorship advice block following this strict template structure:
"Hey [Name], since you're tracking [behavior topic], you should check out [news item tool/concept] today. It directly impacts your work with [user skill/topic] because [reason]. Spend 10 minutes reading their docs to stay ahead."

Example:
"Hey Sarah, since you're tracking Agentic AI and tool integration, check out the enterprise database MCP server released this morning. It bridges the gap between LLMs and live corporate data architectures—a massive skillset gap in enterprise software right now."

Return the suggestions in the following structured JSON format:
{{
  "summary": "A 2-3 sentence overview of the career progression focus area based on this week's trends.",
  "suggestions": [
    {{
      "title": "Short descriptive title (e.g. 'Adopt local model quantization' or 'Explore MCP tooling')",
      "description": "The exact 'Hey [Name], ...' template text computed for this suggestion.",
      "action_item": "A short, actionable instruction (e.g. 'Your Growth Action: Spend 10 minutes reading their deployment markdown script to see how to implement it locally.')",
      "impact": "High | Medium | Low",
      "relevance": "Why this suggestion is critical based on their specific interest or bookmarks."
    }}
  ]
}}

Only output valid JSON. No markdown wrapper blocks.
"""
    else:
        # Market growth suggestions
        prompt = f"""You are a professional venture capitalist and AI market strategist.
Based on the latest news, analyze the overall AI market landscape. Generate 4 strategic recommendations on how to grow the AI market, identify commercial opportunities, and upgrade workflows day-to-day.

Latest AI News & Advancements:
{json.dumps(recent_news_context, indent=2)}

Return the suggestions in the following structured JSON format:
{{
  "summary": "A 2-3 sentence strategic analysis of current market opportunities and structural growth directions in the AI space.",
  "suggestions": [
    {{
      "title": "Market upgrade / Commercial recommendation title",
      "description": "Deep-dive analysis of how this news category can grow the AI market or how developers/enterprises can scale their products.",
      "action_item": "Concrete business / development action item to implement this upgrade.",
      "impact": "High | Medium | Low",
      "relevance": "Underlying market trend or news source that validates this opportunity."
    }}
  ]
}}

Only output valid JSON. No markdown wrapper blocks.
"""

    try:
        gemini = get_gemini_client()
        response_data = await gemini.generate_json(prompt)
    except Exception as exc:
        logger.error("suggestions_generation_error", error=str(exc))
        if settings.is_development:
            logger.info("returning_mock_suggestions_in_dev")
            if suggestion_type == "personalized":
                response_data = {
                    "summary": "Focus on adopting local quantization techniques and MCP servers to optimize resource usage.",
                    "suggestions": [
                        {
                            "title": "Adopt local model quantization",
                            "description": f"Hey {user_name}, since you're tracking local model inference, check out the new quantization repository today. It directly impacts your work with local model deployment because it cuts memory footprint in half. Spend 10 minutes reading their docs to stay ahead.",
                            "action_item": "Your Growth Action: Spend 10 minutes reading their deployment markdown script to see how to implement it locally.",
                            "impact": "High",
                            "relevance": "Matches your preferences for LLMs and local inference."
                        }
                    ]
                }
            else:
                response_data = {
                    "summary": "Commercialize local inference APIs and expand model integrations.",
                    "suggestions": [
                        {
                            "title": "Scale enterprise MCP connector templates",
                            "description": "Enterprises lack ready-to-run MCP servers for secure database access. Providing plug-and-play connectors accelerates commercial adoption.",
                            "action_item": "Concrete business action: Spin up a boilerplate PostgreSQL connector template.",
                            "impact": "High",
                            "relevance": "Matches recent rise in enterprise MCP news."
                        }
                    ]
                }
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to generate suggestions from Gemini: {str(exc)}",
            )

    # Save to Redis cache (TTL: 4 hours)
    try:
        if redis and response_data:
            await redis.set(cache_key, json.dumps(response_data), ttl_seconds=14400)
    except Exception as exc:
        logger.warning("suggestions_cache_write_error", error=str(exc))

    return response_data


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
