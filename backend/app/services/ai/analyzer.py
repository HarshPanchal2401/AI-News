"""
AI Pulse – Article Analyzer & Batch Processor
===============================================
Uses Gemini to extract structured analysis from news articles,
then saves results to the NewsAnalysis table.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_analysis import NewsAnalysis
from app.models.news_article import NewsArticle
from app.services.ai.gemini_client import get_gemini_client
from app.utils.text_utils import estimate_reading_time

logger = get_logger(__name__)

# Valid AI categories
VALID_CATEGORIES = [
    "LLMs", "AI Agents", "Research", "Robotics", "Healthcare",
    "Finance", "Coding", "Open Source", "Enterprise AI", "Safety",
    "Computer Vision", "NLP", "Multimodal", "Hardware", "General AI",
]

ANALYSIS_PROMPT_TEMPLATE = """You are an AI news analyst. Analyze the following AI news article and return a JSON object with EXACTLY these fields:

Article Title: {title}
Article URL: {url}
Article Source: {source}
Article Description: {description}

Return ONLY valid JSON with these exact fields:
{{
  "summary": "A clear, factual 2-4 sentence summary of what this article is about",
  "category": "One of: LLMs, AI Agents, Research, Robotics, Healthcare, Finance, Coding, Open Source, Enterprise AI, Safety, Computer Vision, NLP, Multimodal, Hardware, General AI",
  "companies": ["List of company/organization names mentioned"],
  "keywords": ["5-10 specific keywords from the article"],
  "importance_score": <integer 0-100, where 100 = breakthrough discovery, 50 = significant update, 20 = minor news>,
  "why_it_matters": "1-2 sentences explaining the real-world impact and why this matters to AI practitioners",
  "reading_time_minutes": <estimated minutes to read the full article, integer 1-15>,
  "tags": ["descriptive tags: e.g., breakthrough, open-source, safety, benchmark, funding, product-launch, research-paper, partnership"]
}}

Rules:
- Be factual and objective
- importance_score should reflect genuine significance (most news is 30-60)
- Tags should be specific and descriptive
- companies should only include real, known organizations"""


@dataclass
class AnalysisResult:
    """Structured output from Gemini article analysis."""
    summary: str
    category: str
    companies: list[str]
    keywords: list[str]
    importance_score: float
    why_it_matters: str
    reading_time_minutes: int
    tags: list[str]


class ArticleAnalyzer:
    """
    Analyzes individual news articles using Gemini 2.5 Flash.
    """

    def __init__(self) -> None:
        self.client = get_gemini_client()

    async def analyze(
        self,
        title: str,
        url: str,
        source: str,
        description: str | None = None,
        content_snippet: str | None = None,
    ) -> AnalysisResult:
        """
        Analyze a news article and return structured AI analysis.

        Args:
            title: Article title.
            url: Article URL.
            source: Source name/domain.
            description: Short description or lede.
            content_snippet: First few hundred chars of article body.

        Returns:
            AnalysisResult with all Gemini-extracted fields.
        """
        # Build prompt with available content
        desc = description or content_snippet or "No description available."
        desc = desc[:800]  # Limit to avoid token overflow

        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            title=title,
            url=url,
            source=source,
            description=desc,
        )

        raw = await self.client.generate_json(prompt)

        # Validate and normalize response
        return self._parse_response(raw, title, description or "")

    def _parse_response(
        self, raw: dict, title: str, fallback_desc: str
    ) -> AnalysisResult:
        """Parse and validate Gemini's JSON response."""

        # Validate category
        category = raw.get("category", "General AI")
        if category not in VALID_CATEGORIES:
            category = "General AI"

        # Clamp importance score
        importance = float(raw.get("importance_score", 50))
        importance = max(0.0, min(100.0, importance))

        # Ensure lists
        companies = [str(c) for c in raw.get("companies", []) if c][:10]
        keywords = [str(k) for k in raw.get("keywords", []) if k][:10]
        tags = [str(t) for t in raw.get("tags", []) if t][:10]

        # Estimate reading time fallback
        reading_time = int(raw.get("reading_time_minutes", 3))
        reading_time = max(1, min(15, reading_time))

        return AnalysisResult(
            summary=str(raw.get("summary", fallback_desc[:300])),
            category=category,
            companies=companies,
            keywords=keywords,
            importance_score=importance,
            why_it_matters=str(raw.get("why_it_matters", "")),
            reading_time_minutes=reading_time,
            tags=tags,
        )


class BatchArticleProcessor:
    """
    Processes multiple articles through Gemini analysis with concurrency control.
    Saves results to the database.
    """

    BATCH_CONCURRENCY = 5  # Max parallel Gemini requests

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.analyzer = ArticleAnalyzer()
        self._semaphore = asyncio.Semaphore(self.BATCH_CONCURRENCY)

    async def process_article(self, article: NewsArticle) -> bool:
        """
        Process a single article through Gemini analysis.

        Args:
            article: NewsArticle ORM object with source data.

        Returns:
            True if analysis was saved successfully, False on failure.
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

                # Save analysis to DB
                analysis = NewsAnalysis(
                    article_id=article.id,
                    summary=result.summary,
                    category=result.category,
                    companies=result.companies,
                    keywords=result.keywords,
                    tags=result.tags,
                    importance_score=result.importance_score,
                    why_it_matters=result.why_it_matters,
                    reading_time_minutes=result.reading_time_minutes,
                    model_used=settings.gemini_model,
                )
                self.db.add(analysis)

                # Update article with importance score and ai_processed flag
                article.importance_score = result.importance_score
                article.ai_processed = True

                await self.db.flush()

                logger.debug(
                    "article_analyzed",
                    article_id=str(article.id),
                    category=result.category,
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

    async def process_batch(self, articles: list[NewsArticle]) -> dict[str, int]:
        """
        Process a batch of articles concurrently.

        Args:
            articles: List of unprocessed NewsArticle objects.

        Returns:
            Stats dict: {processed, failed}.
        """
        logger.info("batch_processing_started", count=len(articles))

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
            "batch_processing_complete",
            total=len(articles),
            processed=processed,
            failed=failed,
        )

        return {"processed": processed, "failed": failed}

    async def process_unprocessed(self) -> dict[str, int]:
        """
        Find and process all verified, unprocessed articles.
        Called by the daily scheduler.
        """
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
