"""
AI Pulse – News API Router
============================
Endpoints for browsing, searching, and fetching articles.
"""

from __future__ import annotations

import math
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_optional_user
from app.core.exceptions import NotFoundError
from app.database.connection import get_db
from app.models.news_article import NewsArticle
from app.models.news_analysis import NewsAnalysis
from app.models.user import User
from app.schemas import (
    NewsArticleListResponse,
    NewsArticleResponse,
    NewsListPaginatedResponse,
)
from app.services.cache.redis_client import get_redis_client
from app.utils.date_utils import start_of_day, utcnow
from app.utils.text_utils import normalize_title

router = APIRouter(prefix="/news", tags=["News"])


# ── Live Fetch Endpoint (No DB required) ──────────────────────────────────────

@router.post(
    "/fetch-live",
    summary="Fetch and return today's top important AI news (live and save to DB)",
)
async def fetch_live_news(
    page_size: int = Query(default=12, ge=1, le=30, description="Articles to show initially"),
    days: int = Query(default=3, ge=1, le=7, description="How many days back to look"),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetches live news from all 19 sources, filters to recent articles,
    scores each by importance, saves new ones to the database, and returns
    the top N most important ones.
    """
    from datetime import datetime, timezone, timedelta
    from app.services.news_fetchers.orchestrator import NewsFetchOrchestrator
    from app.models.news_article import NewsArticle
    from app.models.news_analysis import NewsAnalysis
    from app.utils.text_utils import (
        normalize_url,
        normalize_title,
        title_fingerprint,
        content_fingerprint,
    )
    from sqlalchemy import select

    orchestrator = NewsFetchOrchestrator()
    all_articles = await orchestrator.fetch_all()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # ── Sources to completely exclude (repos/products, not news) ─────────────
    EXCLUDED_SOURCES = {"github_trending_ai", "producthunt_ai"}

    # ── Topics to filter OUT (company-specific repos, tutorials, general dev) ─
    BLOCKLIST_KEYWORDS = [
        "github trending", "stars today", "pytorch_geometric", "kohya",
        "how to use", "tutorial", "tailwindcss", "daisyui", "headscale",
        "posthog", "supabase repos", "flutter", "rust crate", "npm package",
        "saadeghi", "juanfont", "bmaltais", "chidiwilliams",
    ]

    # ── Tier 1: AI market events (+40 pts each match) ─────────────────────────
    MARKET_KEYWORDS = [
        "launches", "release", "released", "announces", "unveiled", "introduced",
        "raises", "funding", "acquisition", "acquires", "acquired", "partnership",
        "valuation", "ipo", "investment", "series a", "series b", "series c",
        "beats", "surpasses", "outperforms", "competition", "competitor", "rival",
        "bans", "blocks", "sues", "lawsuit", "regulation", "eu ai act",
    ]

    # ── Tier 2: New AI models & research (+30 pts each match) ─────────────────
    MODEL_KEYWORDS = [
        "gpt", "gemini", "claude", "llama", "mistral", "grok", "qwen", "phi",
        "new model", "model release", "open source model", "fine-tuning",
        "parameter", "context window", "multimodal", "vision model",
        "reasoning", "chain-of-thought", "rlhf", "instruction-tuned",
        "sota", "state-of-the-art", "benchmark", "leaderboard",
    ]

    # ── Tier 3: Research & methods (+20 pts each match) ───────────────────────
    RESEARCH_KEYWORDS = [
        "research", "paper", "study", "breakthrough", "method", "approach",
        "agent", "agentic", "rag", "retrieval", "embedding", "transformer",
        "diffusion", "reinforcement learning", "hallucination", "alignment",
        "safety", "interpretability", "efficiency", "inference", "training",
    ]

    def score_article(article) -> float:
        text = f"{article.title} {article.description or ''}".lower()
        score = 0.0

        # Hard exclude — return negative so they sort to bottom
        if article.source_name in EXCLUDED_SOURCES:
            return -999.0

        # Block irrelevant content
        if any(bl in text for bl in BLOCKLIST_KEYWORDS):
            return -500.0

        # Recency score (still matters — news is time-sensitive)
        if article.published_at:
            age_hours = (now - article.published_at).total_seconds() / 3600
            if age_hours <= 24:
                score += 40
            elif age_hours <= 48:
                score += 25
            elif age_hours <= 72:
                score += 12
        else:
            score += 8

        # Official AI company source (press release / blog = primary source)
        if article.is_official:
            score += 60

        # Trusted tech media
        trusted_media = {"techcrunch_ai", "venturebeat_ai", "mit_tech_review", "google_news_ai"}
        if article.source_name in trusted_media:
            score += 10

        # Tier 1: Market events (most important for you)
        for kw in MARKET_KEYWORDS:
            if kw in text:
                score += 40

        # Tier 2: New model / product launches
        for kw in MODEL_KEYWORDS:
            if kw in text:
                score += 30

        # Tier 3: Research & methods
        for kw in RESEARCH_KEYWORDS:
            if kw in text:
                score += 20

        return score

    # ── Filter to recent only, exclude negatively scored ─────────────────────
    recent = [
        a for a in all_articles
        if (a.published_at is None or a.published_at >= cutoff)
        and score_article(a) > 0   # discard excluded/blocked articles
    ]

    # ── Score and sort ALL recent articles ───────────────────────────────────
    scored = sorted(recent, key=score_article, reverse=True)
    # Cap at 60 total to keep response size reasonable
    all_scored = scored[:60]

    # Map raw models to response list dicts
    articles_dict_list = []
    for a in all_scored:
        articles_dict_list.append({
            "title": a.title,
            "url": a.url,
            "source": a.source_name,
            "source_domain": a.source_domain,
            "description": a.description,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "image_url": a.image_url,
            "is_official": a.is_official,
            "official_company": a.official_company if a.is_official else None,
            "importance_score": round(score_article(a), 1),
        })

    # ── DB Deduplication and Save ─────────────────────────────────────────────
    # Build list of normalized URLs
    url_to_dict = {normalize_url(item["url"]): item for item in articles_dict_list}
    if url_to_dict:
        # Check existing URLs in database
        stmt = select(NewsArticle.normalized_url).where(
            NewsArticle.normalized_url.in_(list(url_to_dict.keys()))
        )
        res = await db.execute(stmt)
        existing_urls = set(res.scalars().all())

        to_insert = []
        for norm_url, article_data in url_to_dict.items():
            if norm_url in existing_urls:
                continue

            # Determine category dynamically
            category = "LLMs"
            text = f"{article_data['title']} {article_data['description'] or ''}".lower()
            if any(k in text for k in ["research", "paper", "arxiv"]):
                category = "Research"
            elif any(k in text for k in ["agent", "reasoning", "decision"]):
                category = "AI Agents"
            elif any(k in text for k in ["robot", "robotic", "hardware", "nvidia"]):
                category = "Robotics"
            elif any(k in text for k in ["code", "coding", "developer", "programmer"]):
                category = "Coding"
            elif any(k in text for k in ["open source", "open-source", "apache"]):
                category = "Open Source"
            elif any(k in text for k in ["medical", "health", "clinical", "hospital"]):
                category = "Healthcare"
            elif any(k in text for k in ["finance", "bank", "stock", "funding", "raises"]):
                category = "Finance"

            t_fp = title_fingerprint(article_data['title'])
            c_fp = content_fingerprint(article_data['title'], article_data['description'] or "")

            try:
                published_time = datetime.fromisoformat(article_data['published_at']) if article_data['published_at'] else now
            except Exception:
                published_time = now

            db_art = NewsArticle(
                title=article_data['title'],
                normalized_title=normalize_title(article_data['title']),
                url=article_data['url'],
                normalized_url=norm_url,
                image_url=article_data['image_url'],
                description=article_data['description'],
                content_snippet=(article_data['description'] or "")[:500],
                published_at=published_time,
                source_domain=article_data['source_domain'],
                title_fingerprint=t_fp,
                content_fingerprint=c_fp,
                is_duplicate=False,
                is_verified=True,
                trust_score=75.0,
                is_official_source=article_data['is_official'],
                ai_processed=True,
                importance_score=article_data['importance_score'],
                final_score=article_data['importance_score'],
                supporting_sources=[],
            )

            db_analysis = NewsAnalysis(
                summary=article_data['description'] or article_data['title'] or "No summary available.",
                category=category,
                companies=[article_data['official_company']] if article_data['is_official'] and article_data['official_company'] else [],
                keywords=[],
                tags=[],
                importance_score=article_data['importance_score'],
                why_it_matters=article_data['title'],
                reading_time_minutes=3,
                model_used="live-fetcher",
            )
            db_art.analysis = db_analysis
            to_insert.append(db_art)

        if to_insert:
            db.add_all(to_insert)
            await db.commit()

    # ── Build response ────────────────────────────────────────────────────────
    return {
        "fetched_total": len(all_articles),
        "recent_count": len(recent),
        "page_size": page_size,           # how many the frontend shows initially
        "total_available": len(articles_dict_list),
        "has_more": len(articles_dict_list) > page_size,
        "days_window": days,
        "articles": articles_dict_list,  # ALL scored articles
    }


@router.get(
    "",
    response_model=NewsListPaginatedResponse,
    summary="Get latest verified AI news articles",
)
async def get_news(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Articles per page"),
    category: str | None = Query(default=None, description="Filter by category"),
    company: str | None = Query(default=None, description="Filter by company name"),
    from_date: date | None = Query(default=None, description="Filter from date (YYYY-MM-DD)"),
    to_date: date | None = Query(default=None, description="Filter to date (YYYY-MM-DD)"),
    sort: str = Query(default="score", pattern="^(score|date|trust)$", description="Sort field"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> NewsListPaginatedResponse:
    """
    Returns paginated, verified AI news articles.
    Supports filtering by category, company, and date range.
    Articles are cached for 5 minutes.
    """
    redis = get_redis_client()
    cache_key = f"news:list:p{page}:l{limit}:cat={category}:co={company}:sort={sort}"
    cached = await redis.get(cache_key)
    if cached and not current_user:
        return NewsListPaginatedResponse(**cached)

    # Build query
    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(
            NewsArticle.is_verified == True,  # noqa: E712
            NewsArticle.is_duplicate == False,  # noqa: E712
            NewsArticle.ai_processed == True,  # noqa: E712
        )
    )

    # Category filter
    if category:
        stmt = stmt.join(NewsAnalysis).where(NewsAnalysis.category == category)
    else:
        stmt = stmt.outerjoin(NewsAnalysis)

    # Company filter
    if company:
        stmt = stmt.where(
            NewsAnalysis.companies.any(company)
            if not category else NewsAnalysis.companies.any(company)
        )

    # Date filters
    if from_date:
        from datetime import datetime, timezone
        stmt = stmt.where(
            NewsArticle.published_at >= datetime.combine(from_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        )
    if to_date:
        from datetime import datetime, timezone
        stmt = stmt.where(
            NewsArticle.published_at <= datetime.combine(to_date, datetime.max.time()).replace(tzinfo=timezone.utc)
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Sort
    if sort == "date":
        stmt = stmt.order_by(NewsArticle.published_at.desc().nullslast())
    elif sort == "trust":
        stmt = stmt.order_by(NewsArticle.trust_score.desc())
    else:
        stmt = stmt.order_by(NewsArticle.final_score.desc())

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    articles = list(result.scalars().all())

    items = [_article_to_list_schema(a) for a in articles]
    pages = max(1, math.ceil(total / limit))

    response = NewsListPaginatedResponse(
        total=total,
        page=page,
        limit=limit,
        pages=pages,
        items=items,
    )

    # Cache for anonymous users
    if not current_user:
        from app.core.config import settings
        await redis.set(cache_key, response.model_dump(), ttl_seconds=settings.cache_ttl_news_latest)

    return response


@router.get(
    "/trending",
    response_model=list[NewsArticleListResponse],
    summary="Get today's top trending AI articles",
)
async def get_trending(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[NewsArticleListResponse]:
    """Returns the highest-ranked articles from today."""
    today_start = start_of_day()
    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(
            NewsArticle.is_verified == True,  # noqa: E712
            NewsArticle.is_duplicate == False,  # noqa: E712
            NewsArticle.ai_processed == True,  # noqa: E712
            NewsArticle.created_at >= today_start,
        )
        .order_by(NewsArticle.final_score.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    articles = list(result.scalars().all())
    return [_article_to_list_schema(a) for a in articles]


@router.get(
    "/search",
    response_model=NewsListPaginatedResponse,
    summary="Full-text search across articles",
)
async def search_news(
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> NewsListPaginatedResponse:
    """Search articles by title, description, keywords, or summary."""
    norm_query = normalize_title(q)
    search_pattern = f"%{norm_query}%"

    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .outerjoin(NewsAnalysis)
        .where(
            NewsArticle.is_verified == True,  # noqa: E712
            NewsArticle.is_duplicate == False,  # noqa: E712
            or_(
                NewsArticle.normalized_title.ilike(search_pattern),
                NewsArticle.description.ilike(f"%{q}%"),
                NewsAnalysis.summary.ilike(f"%{q}%"),
                NewsAnalysis.keywords.any(q.lower()),
            ),
        )
    )

    if category:
        stmt = stmt.where(NewsAnalysis.category == category)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = count_result.scalar_one()

    stmt = stmt.order_by(NewsArticle.final_score.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)

    result = await db.execute(stmt)
    articles = list(result.scalars().all())

    return NewsListPaginatedResponse(
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)),
        items=[_article_to_list_schema(a) for a in articles],
    )


@router.get(
    "/{article_id}",
    response_model=NewsArticleResponse,
    summary="Get full article details by ID",
)
async def get_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> NewsArticleResponse:
    """
    Returns detailed article information including full AI analysis.
    Results are cached for 30 minutes.
    """
    redis = get_redis_client()
    cache_key = f"news:detail:{article_id}"
    cached = await redis.get(cache_key)
    if cached:
        return NewsArticleResponse(**cached)

    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(
            NewsArticle.id == article_id,
            NewsArticle.is_verified == True,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    article = result.scalar_one_or_none()

    if not article:
        raise NotFoundError("Article", article_id)

    # Increment view count
    article.view_count += 1
    await db.commit()

    response = _article_to_detail_schema(article)
    from app.core.config import settings
    await redis.set(cache_key, response.model_dump(), ttl_seconds=settings.cache_ttl_news_detail)

    return response


@router.post(
    "/{article_id}/analyze",
    response_model=NewsArticleResponse,
    summary="Trigger/generate AI summary and analysis for a specific article",
)
async def analyze_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> NewsArticleResponse:
    """
    Triggers/gets Gemini analysis for the specified article.
    """
    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(NewsArticle.id == article_id)
    )
    result = await db.execute(stmt)
    article = result.scalar_one_or_none()
    if not article:
        raise NotFoundError("Article", article_id)
        
    if not article.analysis:
        from app.services.ai.analyzer import BatchArticleProcessor
        processor = BatchArticleProcessor(db)
        await processor.process_article(article)
        
        # Refresh article to include analysis
        stmt = (
            select(NewsArticle)
            .options(selectinload(NewsArticle.analysis))
            .where(NewsArticle.id == article_id)
        )
        result = await db.execute(stmt)
        article = result.scalar_one()

    # Clear cache
    redis = get_redis_client()
    cache_key = f"news:detail:{article_id}"
    await redis.delete(cache_key)

    return _article_to_detail_schema(article)


@router.get(
    "/daily-brief",
    response_model=list[NewsArticleListResponse],
    summary="Get personalized daily brief",
)
async def get_daily_brief(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NewsArticleListResponse]:
    """
    Returns top 5 articles for the user based on their preferences.
    """
    from app.models.user import UserPreferences
    from sqlalchemy import desc
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    prefs = result.scalar_one_or_none()
    from app.models.news_analysis import NewsAnalysis
    
    stmt = (
        select(NewsArticle)
        .options(selectinload(NewsArticle.analysis))
        .where(
            NewsArticle.is_verified == True,
            NewsArticle.is_duplicate == False,
        )
    )

    if prefs:
        from sqlalchemy import or_, not_
        
        match_conditions = []
        if prefs.favorite_categories:
            match_conditions.append(NewsAnalysis.category.in_(prefs.favorite_categories))
            
        if prefs.favorite_companies:
            for comp in prefs.favorite_companies:
                match_conditions.append(NewsAnalysis.companies.any(comp))
                
        if prefs.favorite_topics:
            for topic in prefs.favorite_topics:
                match_conditions.append(NewsAnalysis.keywords.any(topic.lower()))
                
        if match_conditions:
            stmt = stmt.outerjoin(NewsAnalysis, NewsArticle.id == NewsAnalysis.article_id)
            stmt = stmt.where(or_(*match_conditions))
            
        if prefs.blocked_topics:
            if not match_conditions:
                stmt = stmt.outerjoin(NewsAnalysis, NewsArticle.id == NewsAnalysis.article_id)
            for topic in prefs.blocked_topics:
                stmt = stmt.where(not_(NewsAnalysis.keywords.any(topic.lower())))

    stmt = stmt.order_by(desc(NewsArticle.final_score)).limit(5)
    result = await db.execute(stmt)
    articles = list(result.scalars().all())

    # Fallback: if no personalized matches found, return top 5 articles from the database
    if not articles:
        fallback_stmt = (
            select(NewsArticle)
            .options(selectinload(NewsArticle.analysis))
            .where(
                NewsArticle.is_verified == True,
                NewsArticle.is_duplicate == False,
            )
            .order_by(desc(NewsArticle.priority_score), desc(NewsArticle.created_at))
            .limit(5)
        )
        fallback_result = await db.execute(fallback_stmt)
        articles = list(fallback_result.scalars().all())

    return [_article_to_list_schema(a) for a in articles]


# ── Schema Helpers ────────────────────────────────────────────────────────────

def _article_to_list_schema(article: NewsArticle) -> NewsArticleListResponse:
    """Convert ORM object to list-view schema."""
    analysis = article.analysis
    return NewsArticleListResponse(
        id=article.id,
        title=article.title,
        url=article.url,
        image_url=article.image_url,
        description=article.description,
        published_at=article.published_at,
        source_domain=article.source_domain,
        trust_score=article.trust_score,
        final_score=article.final_score,
        category=analysis.category if analysis else None,
        reading_time_minutes=analysis.reading_time_minutes if analysis else None,
        companies=analysis.companies if analysis else [],
        tags=analysis.tags if analysis else [],
        created_at=article.created_at,
    )


def _article_to_detail_schema(article: NewsArticle) -> NewsArticleResponse:
    """Convert ORM object to detail-view schema."""
    from app.schemas import NewsAnalysisResponse

    analysis_schema = None
    if article.analysis:
        a = article.analysis
        analysis_schema = NewsAnalysisResponse(
            summary=a.summary,
            executive_summary=a.executive_summary,
            key_takeaways=a.key_takeaways or [],
            category=a.category,
            subcategory=a.subcategory,
            event_type=a.event_type,
            companies=a.companies or [],
            keywords=a.keywords or [],
            tags=a.tags or [],
            importance_score=a.importance_score,
            why_it_matters=a.why_it_matters,
            reading_time_minutes=a.reading_time_minutes,
            products_mentioned=a.products_mentioned or [],
            people_mentioned=a.people_mentioned or [],
            technologies_mentioned=a.technologies_mentioned or [],
            programming_languages=a.programming_languages or [],
            models_mentioned=a.models_mentioned or [],
            funding_amount=a.funding_amount,
            funding_currency=a.funding_currency,
            research_paper_url=a.research_paper_url,
            arxiv_id=a.arxiv_id,
            countries_affected=a.countries_affected or [],
            industries_affected=a.industries_affected or [],
            market_impact=a.market_impact,
            business_opportunities=a.business_opportunities,
            risks=a.risks,
            sentiment=a.sentiment,
            urgency=a.urgency,
            confidence_score=a.confidence_score,
        )

    return NewsArticleResponse(
        id=article.id,
        title=article.title,
        url=article.url,
        image_url=article.image_url,
        description=article.description,
        author=article.author,
        published_at=article.published_at,
        source_domain=article.source_domain,
        trust_score=article.trust_score,
        importance_score=article.importance_score,
        final_score=article.final_score,
        is_official_source=article.is_official_source,
        view_count=article.view_count,
        bookmark_count=article.bookmark_count,
        supporting_sources=article.supporting_sources,
        analysis=analysis_schema,
        created_at=article.created_at,
    )
