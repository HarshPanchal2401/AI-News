"""
AI News Intelligence Engine – News Fetch Orchestrator
=======================================================
Runs all ~30 fetchers concurrently, collects results, and hands off
to the pipeline. Sources are organized by trust tier and category.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger
from app.services.news_fetchers.arxiv_fetcher import ArXivFetcher
from app.services.news_fetchers.base import RawArticle
from app.services.news_fetchers.community_fetchers import (
    GitHubReleasesFetcher,
    HackerNewsFetcher,
    RedditAIFetcher,
)
from app.services.news_fetchers.rss_fetcher import (
    AnthropicFetcher,
    ArsTechnicaFetcher,
    BloombergTechFetcher,
    CohereFetcher,
    DeepMindFetcher,
    GoogleAIFetcher,
    HuggingFaceFetcher,
    MetaAIFetcher,
    MicrosoftAIFetcher,
    MistralFetcher,
    MITTechReviewFetcher,
    NVIDIAFetcher,
    PapersWithCodeFetcher,
    ReutersAIFetcher,
    StabilityAIFetcher,
    TechCrunchAIFetcher,
    TheVergeFetcher,
    VentureBeatAIFetcher,
    WiredAIFetcher,
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


# ── Source Metadata Registry ──────────────────────────────────────────────────
# Maps source_name -> metadata for analytics and trust scoring
SOURCE_REGISTRY: dict[str, dict] = {
    # Official Company Blogs (Tier 0 — highest trust)
    "openai_blog":           {"tier": 0, "category": "official", "company": "OpenAI"},
    "google_ai_blog":        {"tier": 0, "category": "official", "company": "Google"},
    "deepmind_blog":         {"tier": 0, "category": "official", "company": "Google DeepMind"},
    "anthropic_news":        {"tier": 0, "category": "official", "company": "Anthropic"},
    "microsoft_ai_blog":     {"tier": 0, "category": "official", "company": "Microsoft"},
    "meta_ai_blog":          {"tier": 0, "category": "official", "company": "Meta"},
    "nvidia_ai_blog":        {"tier": 0, "category": "official", "company": "NVIDIA"},
    "huggingface_blog":      {"tier": 0, "category": "official", "company": "Hugging Face"},
    "mistral_news":          {"tier": 0, "category": "official", "company": "Mistral AI"},
    "xai_news":              {"tier": 0, "category": "official", "company": "xAI"},
    "perplexity_blog":       {"tier": 0, "category": "official", "company": "Perplexity"},
    "stability_ai_news":     {"tier": 0, "category": "official", "company": "Stability AI"},
    "cohere_blog":           {"tier": 0, "category": "official", "company": "Cohere"},
    # Research
    "arxiv_ai":              {"tier": 1, "category": "research"},
    "papers_with_code":      {"tier": 1, "category": "research"},
    # Tier-1 Technology Media
    "techcrunch_ai":         {"tier": 1, "category": "media"},
    "venturebeat_ai":        {"tier": 1, "category": "media"},
    "mit_tech_review":       {"tier": 1, "category": "media"},
    "reuters_technology":    {"tier": 1, "category": "media"},
    "bloomberg_tech":        {"tier": 1, "category": "media"},
    "wired_ai":              {"tier": 1, "category": "media"},
    "theverge_ai":           {"tier": 1, "category": "media"},
    "arstechnica_ai":        {"tier": 1, "category": "media"},
    # Developer Sources
    "github_trending_ai":    {"tier": 2, "category": "developer"},
    "github_releases_ai":    {"tier": 2, "category": "developer"},
    # Communities
    "reddit_ai":             {"tier": 2, "category": "community"},
    "hacker_news":           {"tier": 2, "category": "community"},
    "producthunt_ai":        {"tier": 2, "category": "community"},
    # Aggregators
    "google_news_ai":        {"tier": 3, "category": "aggregator"},
}


class NewsFetchOrchestrator:
    """
    Orchestrates concurrent fetching from all ~30 AI news sources.

    Sources are grouped by trust tier:
      Tier 0: Official company blogs (highest trust)
      Tier 1: Research + Tier-1 media
      Tier 2: Developer + community sources
      Tier 3: Aggregators (lowest individual trust, useful for discovery)

    Failures in individual fetchers are isolated — they don't stop others.
    Returns a URL-deduplicated list of RawArticle objects ready for the pipeline.
    """

    def __init__(self) -> None:
        self._fetchers = [
            # ── Tier 0: Official Company Blogs (highest trust) ─────────────────
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
            StabilityAIFetcher(),
            CohereFetcher(),
            # ── Tier 1: Research ───────────────────────────────────────────────
            ArXivFetcher(),
            PapersWithCodeFetcher(),
            # ── Tier 1: Technology Media ───────────────────────────────────────
            TechCrunchAIFetcher(),
            VentureBeatAIFetcher(),
            MITTechReviewFetcher(),
            ReutersAIFetcher(),
            BloombergTechFetcher(),
            WiredAIFetcher(),
            TheVergeFetcher(),
            ArsTechnicaFetcher(),
            # ── Tier 2: Developer Sources ──────────────────────────────────────
            GitHubTrendingFetcher(),
            GitHubReleasesFetcher(),
            # ── Tier 2: Communities ────────────────────────────────────────────
            RedditAIFetcher(),
            HackerNewsFetcher(),
            ProductHuntAIFetcher(),
            # ── Tier 3: Aggregators / Discovery ───────────────────────────────
            GoogleNewsFetcher(),
        ]

    @property
    def source_count(self) -> int:
        return len(self._fetchers)

    async def fetch_all(self) -> list[RawArticle]:
        """
        Fetch from all sources concurrently.

        Returns:
            List of raw articles, URL-deduplicated, sorted by trust tier,
            ready for the validation + intelligence pipeline.
        """
        logger.info(
            "orchestrator_started",
            source_count=self.source_count,
        )

        # Run all fetchers concurrently
        tasks = [fetcher.safe_fetch() for fetcher in self._fetchers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all articles with per-source stats
        all_articles: list[RawArticle] = []
        source_stats: dict[str, int] = {}
        errors: list[str] = []

        for i, result in enumerate(results):
            fetcher = self._fetchers[i]
            source = fetcher.SOURCE_NAME

            if isinstance(result, Exception):
                logger.error("fetcher_exception", source=source, error=str(result))
                source_stats[source] = 0
                errors.append(source)
                continue

            articles: list[RawArticle] = result
            source_stats[source] = len(articles)
            all_articles.extend(articles)

        # URL-deduplicate (official sources sorted first)
        deduped = self._deduplicate_by_url(all_articles)

        logger.info(
            "orchestrator_completed",
            total_raw=len(all_articles),
            after_url_dedup=len(deduped),
            sources_ok=self.source_count - len(errors),
            sources_failed=len(errors),
            source_stats=source_stats,
        )

        return deduped

    def _deduplicate_by_url(self, articles: list[RawArticle]) -> list[RawArticle]:
        """
        First-pass URL deduplication.
        Sorts: official (tier 0) first, then by publication date desc.
        """
        def sort_key(a: RawArticle) -> tuple:
            tier = SOURCE_REGISTRY.get(a.source_name, {}).get("tier", 9)
            ts = -(a.published_at.timestamp() if a.published_at else 0)
            return (tier, ts)

        sorted_articles = sorted(articles, key=sort_key)

        seen_urls: set[str] = set()
        unique: list[RawArticle] = []

        for article in sorted_articles:
            norm_url = article.url.strip().rstrip("/").lower()
            if norm_url not in seen_urls:
                seen_urls.add(norm_url)
                unique.append(article)

        return unique

    def get_source_registry(self) -> dict[str, dict]:
        """Return the source metadata registry for analytics."""
        return SOURCE_REGISTRY
