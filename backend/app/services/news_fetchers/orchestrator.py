"""
AI Pulse – News Fetch Orchestrator
=====================================
Runs all fetchers concurrently, collects results, and hands off to pipeline.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger
from app.services.news_fetchers.arxiv_fetcher import ArXivFetcher
from app.services.news_fetchers.base import RawArticle
from app.services.news_fetchers.rss_fetcher import (
    AnthropicFetcher,
    DeepMindFetcher,
    GoogleAIFetcher,
    HuggingFaceFetcher,
    MetaAIFetcher,
    MicrosoftAIFetcher,
    MistralFetcher,
    MITTechReviewFetcher,
    NVIDIAFetcher,
    ReutersAIFetcher,
    TechCrunchAIFetcher,
    VentureBeatAIFetcher,
)
from app.services.news_fetchers.scrapers import (
    GitHubTrendingFetcher,
    GoogleNewsFetcher,
    OpenAIFetcher,
    PerplexityFetcher,
    ProductHuntAIFetcher,
    XAIFetcher,
)

logger = get_logger(__name__)


class NewsFetchOrchestrator:
    """
    Orchestrates concurrent fetching from all 20 news sources.

    Runs all fetchers in parallel using asyncio.gather.
    Failures in individual fetchers are isolated — they don't stop other fetchers.
    Returns a deduplicated-by-URL list of raw articles.
    """

    def __init__(self) -> None:
        self._fetchers = [
            # ── Official Company Blogs (highest trust) ─────────────────────────
            OpenAIFetcher(),
            GoogleAIFetcher(),
            DeepMindFetcher(),
            AnthropicFetcher(),
            MicrosoftAIFetcher(),
            MetaAIFetcher(),
            NVIDIAFetcher(),
            HuggingFaceFetcher(),
            MistralFetcher(),
            XAIFetcher(),
            PerplexityFetcher(),
            # ── Tech Media ────────────────────────────────────────────────────
            TechCrunchAIFetcher(),
            VentureBeatAIFetcher(),
            MITTechReviewFetcher(),
            ReutersAIFetcher(),
            # ── Aggregators / Discovery ────────────────────────────────────────
            GoogleNewsFetcher(),
            ArXivFetcher(),
            GitHubTrendingFetcher(),
            ProductHuntAIFetcher(),
        ]

    async def fetch_all(self) -> list[RawArticle]:
        """
        Fetch from all sources concurrently.

        Returns:
            List of raw articles, URL-deduplicated, ready for the pipeline.
        """
        logger.info("orchestrator_started", source_count=len(self._fetchers))

        # Run all fetchers concurrently
        tasks = [fetcher.safe_fetch() for fetcher in self._fetchers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all articles
        all_articles: list[RawArticle] = []
        source_stats: dict[str, int] = {}

        for i, result in enumerate(results):
            fetcher = self._fetchers[i]
            source = fetcher.SOURCE_NAME

            if isinstance(result, Exception):
                logger.error("fetcher_exception", source=source, error=str(result))
                source_stats[source] = 0
                continue

            articles: list[RawArticle] = result
            source_stats[source] = len(articles)
            all_articles.extend(articles)

        # First-pass deduplication by URL
        deduped = self._deduplicate_by_url(all_articles)

        logger.info(
            "orchestrator_completed",
            total_raw=len(all_articles),
            after_url_dedup=len(deduped),
            source_stats=source_stats,
        )

        return deduped

    def _deduplicate_by_url(self, articles: list[RawArticle]) -> list[RawArticle]:
        """
        First-pass URL deduplication.
        Keeps the first occurrence of each URL (official sources sorted first).
        """
        # Sort: official sources first, then by published_at desc
        sorted_articles = sorted(
            articles,
            key=lambda a: (
                not a.is_official,                        # Official first (False < True)
                -(a.published_at.timestamp() if a.published_at else 0),  # Newest first
            ),
        )

        seen_urls: set[str] = set()
        unique: list[RawArticle] = []

        for article in sorted_articles:
            norm_url = article.url.strip().rstrip("/").lower()
            if norm_url not in seen_urls:
                seen_urls.add(norm_url)
                unique.append(article)

        return unique
