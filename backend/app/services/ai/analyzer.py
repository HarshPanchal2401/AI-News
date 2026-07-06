"""
AI News Intelligence Engine – Article Analyzer & Batch Processor
==================================================================
Uses Gemini to extract full 25-field structured analysis from news articles,
then saves results to the NewsAnalysis table and updates the parent NewsEvent.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_analysis import NewsAnalysis
from app.models.news_article import NewsArticle
from app.models.news_event import NewsEvent
from app.services.ai.gemini_client import get_gemini_client
from app.services.priority_engine import PriorityEngine
from app.utils.text_utils import estimate_reading_time

logger = get_logger(__name__)

# Valid AI categories
VALID_CATEGORIES = [
    "LLMs", "AI Agents", "Research", "Robotics", "Healthcare",
    "Finance", "Coding", "Open Source", "Enterprise AI", "Safety",
    "Computer Vision", "NLP", "Multimodal", "Hardware", "General AI",
    "Education", "Infrastructure",
]

VALID_SENTIMENTS = {"positive", "negative", "neutral"}
VALID_URGENCIES = {"breaking", "high", "medium", "low"}
VALID_EVENT_TYPES = {
    "product_launch", "model_release", "funding", "acquisition",
    "research_paper", "open_source_release", "benchmark",
    "security_incident", "government_regulation", "startup_launch",
    "developer_tool", "framework", "api_release", "infrastructure",
    "gpu", "robotics", "ai_agent", "coding_ai", "healthcare_ai",
    "education_ai", "finance_ai",
}

# ── Full 25-Field Analysis Prompt ─────────────────────────────────────────────
ANALYSIS_PROMPT_V2 = """You are an expert AI industry analyst. Analyze this AI news article and return a JSON object with EXACTLY the fields below. Be accurate, specific, and factual.

Article Title: {title}
Article URL: {url}
Article Source: {source}
Article Content: {content}

Return ONLY valid JSON (no markdown, no code blocks) with these exact fields:
{{
  "summary": "Clear, factual 2-4 sentence summary of what this article reports",
  "executive_summary": "5-8 sentence deeper analysis including context, significance, and implications for the AI industry",
  "key_takeaways": ["3-5 bullet points as strings, each a complete standalone insight"],
  "why_it_matters": "1-2 sentences on real-world impact for AI practitioners and businesses",
  "category": "One of: LLMs, AI Agents, Research, Robotics, Healthcare, Finance, Coding, Open Source, Enterprise AI, Safety, Computer Vision, NLP, Multimodal, Hardware, General AI, Education, Infrastructure",
  "subcategory": "Specific subcategory e.g. 'Reasoning Models', 'Image Generation', 'AI Chips', 'Model Training'",
  "event_type": "One of: product_launch, model_release, funding, acquisition, research_paper, open_source_release, benchmark, security_incident, government_regulation, startup_launch, developer_tool, framework, api_release, infrastructure, gpu, robotics, ai_agent, coding_ai, healthcare_ai, education_ai, finance_ai",
  "keywords": ["5-10 specific technical keywords from the article"],
  "tags": ["descriptive tags: e.g., breakthrough, open-source, safety, benchmark, funding, product-launch, research-paper, partnership, multimodal"],
  "companies": ["Exact names of companies/organizations mentioned"],
  "products_mentioned": ["Specific AI products, tools, or services mentioned"],
  "people_mentioned": ["Notable individuals mentioned (CEO names, researchers, etc.)"],
  "technologies_mentioned": ["Specific technologies mentioned (transformers, RLHF, RAG, etc.)"],
  "programming_languages": ["Programming languages mentioned if any"],
  "models_mentioned": ["AI model names mentioned (GPT-4o, Claude 3.5, Gemini 1.5, Llama 3, etc.)"],
  "funding_amount": <number in USD millions if funding article, else null>,
  "funding_currency": "USD" or null,
  "research_paper_url": "URL to paper if mentioned" or null,
  "arxiv_id": "arXiv ID like 2401.12345 if applicable" or null,
  "countries_affected": ["Countries mentioned as affected or involved"],
  "industries_affected": ["Industry sectors affected: healthcare, finance, education, etc."],
  "market_impact": "1-2 sentences on market/competitive impact",
  "business_opportunities": "1-2 sentences on opportunities this creates for businesses",
  "risks": "1-2 sentences on risks or concerns raised",
  "sentiment": "positive, negative, or neutral",
  "urgency": "breaking, high, medium, or low",
  "confidence_score": <integer 60-100, your confidence in this analysis>,
  "importance_score": <integer 0-100, where 95+=breakthrough/historic, 80-94=major news, 60-79=significant, 40-59=noteworthy, 0-39=minor>,
  "reading_time_minutes": <estimated minutes to read full article, integer 1-15>
}}

Rules:
- Be factual and objective. Only include verified information from the article.
- importance_score: Most news is 30-60. A new GPT-5 would be 95+. A minor update is 20.
- funding_amount: Normalize to USD millions (e.g., $500M = 500, $2B = 2000).
- Return null for fields where information is not available in the article.
- companies: Only include real, verified organization names."""


@dataclass
class AnalysisResult:
    """Structured output from Gemini article analysis (v2 — 25 fields)."""
    summary: str
    executive_summary: str
    key_takeaways: list[str]
    why_it_matters: str
    category: str
    subcategory: str | None
    event_type: str | None
    keywords: list[str]
    tags: list[str]
    companies: list[str]
    products_mentioned: list[str]
    people_mentioned: list[str]
    technologies_mentioned: list[str]
    programming_languages: list[str]
    models_mentioned: list[str]
    funding_amount: float | None
    funding_currency: str | None
    research_paper_url: str | None
    arxiv_id: str | None
    countries_affected: list[str]
    industries_affected: list[str]
    market_impact: str | None
    business_opportunities: str | None
    risks: str | None
    sentiment: str
    urgency: str
    confidence_score: float
    importance_score: float
    reading_time_minutes: int


class ArticleAnalyzer:
    """
    Analyzes individual news articles using Gemini.
    Generates full 25-field AI enrichment.
    """

    def __init__(self) -> None:
        self.client = get_gemini_client()
        self.priority_engine = PriorityEngine()

    async def analyze(
        self,
        title: str,
        url: str,
        source: str,
        description: str | None = None,
        content_snippet: str | None = None,
    ) -> AnalysisResult:
        """
        Analyze a news article and return full structured AI analysis.

        Args:
            title: Article title.
            url: Article URL.
            source: Source name/domain.
            description: Short description or lede.
            content_snippet: First few hundred chars of article body.

        Returns:
            AnalysisResult with all 25 Gemini-extracted fields.
        """
        content = description or content_snippet or "No content available."
        content = content[:1200]  # Cap to control token usage

        prompt = ANALYSIS_PROMPT_V2.format(
            title=title,
            url=url,
            source=source,
            content=content,
        )

        raw = await self.client.generate_json(prompt)
        return self._parse_response(raw, title, content)

    def _parse_response(
        self, raw: dict, title: str, fallback_content: str
    ) -> AnalysisResult:
        """Parse and validate Gemini's JSON response."""

        def safe_list(key: str, max_items: int = 15) -> list[str]:
            items = raw.get(key, []) or []
            return [str(i) for i in items if i][:max_items]

        def safe_str(key: str, fallback: str = "") -> str:
            val = raw.get(key)
            return str(val) if val else fallback

        def safe_float(key: str, default: float = 0.0, lo: float = 0.0, hi: float = 100.0) -> float:
            try:
                val = float(raw.get(key, default))
                return max(lo, min(hi, val))
            except (TypeError, ValueError):
                return default

        # Validate category
        category = raw.get("category", "General AI")
        if category not in VALID_CATEGORIES:
            category = "General AI"

        # Validate event_type
        event_type = raw.get("event_type")
        if event_type not in VALID_EVENT_TYPES:
            event_type = None

        # Validate sentiment
        sentiment = raw.get("sentiment", "neutral")
        if sentiment not in VALID_SENTIMENTS:
            sentiment = "neutral"

        # Validate urgency
        urgency = raw.get("urgency", "medium")
        if urgency not in VALID_URGENCIES:
            urgency = "medium"

        # Funding amount
        funding_amount = None
        try:
            fa = raw.get("funding_amount")
            if fa is not None and fa != "null":
                funding_amount = float(fa)
        except (TypeError, ValueError):
            pass

        return AnalysisResult(
            summary=safe_str("summary", fallback_content[:300]),
            executive_summary=safe_str("executive_summary"),
            key_takeaways=safe_list("key_takeaways", 5),
            why_it_matters=safe_str("why_it_matters"),
            category=category,
            subcategory=safe_str("subcategory") or None,
            event_type=event_type,
            keywords=safe_list("keywords", 10),
            tags=safe_list("tags", 10),
            companies=safe_list("companies", 10),
            products_mentioned=safe_list("products_mentioned", 10),
            people_mentioned=safe_list("people_mentioned", 10),
            technologies_mentioned=safe_list("technologies_mentioned", 10),
            programming_languages=safe_list("programming_languages", 5),
            models_mentioned=safe_list("models_mentioned", 10),
            funding_amount=funding_amount,
            funding_currency=safe_str("funding_currency") or None,
            research_paper_url=safe_str("research_paper_url") or None,
            arxiv_id=safe_str("arxiv_id") or None,
            countries_affected=safe_list("countries_affected", 10),
            industries_affected=safe_list("industries_affected", 10),
            market_impact=safe_str("market_impact") or None,
            business_opportunities=safe_str("business_opportunities") or None,
            risks=safe_str("risks") or None,
            sentiment=sentiment,
            urgency=urgency,
            confidence_score=safe_float("confidence_score", 70.0, 0.0, 100.0),
            importance_score=safe_float("importance_score", 50.0, 0.0, 100.0),
            reading_time_minutes=max(1, min(15, int(raw.get("reading_time_minutes", 3) or 3))),
        )


class BatchArticleProcessor:
    """
    Processes multiple articles through Gemini analysis with concurrency control.
    Saves results to the database and updates parent NewsEvents.
    """

    BATCH_CONCURRENCY = 5  # Max parallel Gemini requests

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.analyzer = ArticleAnalyzer()
        self.priority_engine = PriorityEngine()
        self._semaphore = asyncio.Semaphore(self.BATCH_CONCURRENCY)

    async def process_article(self, article: NewsArticle) -> bool:
        """
        Process a single article through Gemini analysis.

        Saves the full NewsAnalysis and updates the article + parent Event.
        """
        async with self._semaphore:
            try:
                result = await self.analyzer.analyze(
                    title=article.title,
                    url=article.url,
                    source=article.source_domain,
                    description=article.description,
                    content_snippet=article.content_snippet,
                )

                # Build or update NewsAnalysis
                analysis = NewsAnalysis(
                    article_id=article.id,
                    summary=result.summary,
                    executive_summary=result.executive_summary,
                    key_takeaways=result.key_takeaways,
                    why_it_matters=result.why_it_matters,
                    category=result.category,
                    subcategory=result.subcategory,
                    event_type=result.event_type,
                    keywords=result.keywords,
                    tags=result.tags,
                    companies=result.companies,
                    products_mentioned=result.products_mentioned,
                    people_mentioned=result.people_mentioned,
                    technologies_mentioned=result.technologies_mentioned,
                    programming_languages=result.programming_languages,
                    models_mentioned=result.models_mentioned,
                    funding_amount=result.funding_amount,
                    funding_currency=result.funding_currency,
                    research_paper_url=result.research_paper_url,
                    arxiv_id=result.arxiv_id,
                    countries_affected=result.countries_affected,
                    industries_affected=result.industries_affected,
                    market_impact=result.market_impact,
                    business_opportunities=result.business_opportunities,
                    risks=result.risks,
                    sentiment=result.sentiment,
                    urgency=result.urgency,
                    confidence_score=result.confidence_score,
                    importance_score=result.importance_score,
                    reading_time_minutes=result.reading_time_minutes,
                    model_used=settings.gemini_model,
                    prompt_version="v2",
                )
                self.db.add(analysis)

                # Update article
                article.importance_score = result.importance_score
                article.ai_processed = True

                # Update parent Event with richer AI data
                if article.event_id:
                    await self._enrich_event(article.event_id, result)

                await self.db.flush()

                logger.debug(
                    "article_analyzed_v2",
                    article_id=str(article.id),
                    category=result.category,
                    event_type=result.event_type,
                    importance=result.importance_score,
                )
                return True

            except Exception as exc:
                logger.error(
                    "article_analysis_failed",
                    article_id=str(article.id),
                    title=article.title[:60],
                    error=str(exc),
                )
                return False

    async def _enrich_event(self, event_id, result: AnalysisResult) -> None:
        """
        Update the parent NewsEvent with AI-extracted metadata.
        Only updates fields that are currently empty.
        """
        try:
            stmt = select(NewsEvent).where(NewsEvent.id == event_id).limit(1)
            db_result = await self.db.execute(stmt)
            event = db_result.scalar_one_or_none()
            if not event:
                return

            # Update event fields from analysis (merge, don't overwrite)
            if result.category and result.category != "General AI":
                event.category = result.category
            if result.subcategory:
                event.subcategory = result.subcategory
            if result.event_type:
                event.event_type = result.event_type
            if result.companies:
                merged = list(set(list(event.companies or []) + result.companies))
                event.companies = merged[:15]
            if result.products_mentioned:
                merged = list(set(list(event.products_mentioned or []) + result.products_mentioned))
                event.products_mentioned = merged[:10]
            if result.people_mentioned:
                merged = list(set(list(event.people_mentioned or []) + result.people_mentioned))
                event.people_mentioned = merged[:10]
            if result.technologies_mentioned:
                event.technologies_mentioned = list(set(
                    list(event.technologies_mentioned or []) + result.technologies_mentioned
                ))[:15]
            if result.models_mentioned:
                event.models_mentioned = list(set(
                    list(event.models_mentioned or []) + result.models_mentioned
                ))[:10]
            if result.keywords:
                event.keywords = list(set(list(event.keywords or []) + result.keywords))[:15]
            if result.tags:
                event.tags = list(set(list(event.tags or []) + result.tags))[:15]
            if result.funding_amount and not event.funding_amount:
                event.funding_amount = result.funding_amount
                event.funding_currency = result.funding_currency
            if result.arxiv_id and not event.arxiv_id:
                event.arxiv_id = result.arxiv_id
                event.research_paper_url = result.research_paper_url
            if result.countries_affected:
                event.countries_affected = list(set(
                    list(event.countries_affected or []) + result.countries_affected
                ))[:10]
            if result.industries_affected:
                event.industries_affected = list(set(
                    list(event.industries_affected or []) + result.industries_affected
                ))[:10]
            if not event.market_impact and result.market_impact:
                event.market_impact = result.market_impact
            if not event.business_opportunities and result.business_opportunities:
                event.business_opportunities = result.business_opportunities
            if not event.risks and result.risks:
                event.risks = result.risks
            if not event.summary and result.summary:
                event.summary = result.summary
            if not event.executive_summary and result.executive_summary:
                event.executive_summary = result.executive_summary
            if not event.key_takeaways and result.key_takeaways:
                event.key_takeaways = result.key_takeaways

            event.sentiment = result.sentiment
            event.urgency = result.urgency
            event.confidence_score = result.confidence_score

            # Re-score priority with richer data
            priority_result = self.priority_engine.compute(
                published_at=event.published_at,
                source_domains=list(event.source_domains or []),
                source_count=event.source_count,
                event_type=result.event_type,
                companies=result.companies,
                funding_amount=result.funding_amount,
            )
            event.priority_score = priority_result.priority_score
            event.freshness_score = priority_result.freshness_score
            event.trust_score = priority_result.trust_score
            event.impact_score = priority_result.impact_score
            event.is_breaking = priority_result.is_breaking

        except Exception as exc:
            logger.warning("event_enrichment_failed", event_id=str(event_id), error=str(exc))

    async def process_batch(self, articles: list[NewsArticle]) -> dict[str, int]:
        """Process a batch of articles concurrently."""
        logger.info("batch_processing_started_v2", count=len(articles))

        tasks = [self.process_article(article) for article in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = sum(1 for r in results if r is True)
        failed = len(results) - processed

        try:
            await self.db.commit()
        except Exception as exc:
            logger.error("batch_commit_failed", error=str(exc))
            await self.db.rollback()

        logger.info(
            "batch_processing_complete_v2",
            total=len(articles),
            processed=processed,
            failed=failed,
        )

        return {"processed": processed, "failed": failed}

    async def process_unprocessed(self) -> dict[str, int]:
        """Find and process all verified, unprocessed articles."""
        stmt = (
            select(NewsArticle)
            .where(
                NewsArticle.is_verified == True,  # noqa: E712
                NewsArticle.ai_processed == False,  # noqa: E712
                NewsArticle.is_duplicate == False,  # noqa: E712
            )
            .order_by(NewsArticle.trust_score.desc())
            .limit(100)
        )
        result = await self.db.execute(stmt)
        articles = list(result.scalars().all())

        if not articles:
            logger.info("no_unprocessed_articles")
            return {"processed": 0, "failed": 0}

        return await self.process_batch(articles)
