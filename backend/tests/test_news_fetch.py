"""
AI Pulse - News Fetcher Smoke Tests
======================================
Tests that each news source fetcher can actually return real articles.
These tests make LIVE network requests - no mocking.

Run with:
    pytest tests/test_news_fetch.py -v -s

Or run a single fetcher:
    pytest tests/test_news_fetch.py::test_google_ai_fetch -v -s

Results are printed to stdout so you can see exactly what each fetcher returns.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the backend/app package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("APP_ENV", "testing")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_articles(source_name: str, articles: list) -> None:
    """Pretty-print fetched articles to stdout."""
    print(f"\n{'='*60}")
    print(f"  SOURCE: {source_name}  -  {len(articles)} article(s) fetched")
    print(f"{'='*60}")
    if not articles:
        print("  WARNING: NO ARTICLES RETURNED")
        return
    for i, a in enumerate(articles[:5], 1):
        print(f"\n  [{i}] {a.title[:80]}")
        print(f"       URL: {a.url[:80]}")
        if a.published_at:
            print(f"       Date: {a.published_at}")
        if a.description:
            print(f"       Desc: {str(a.description)[:100]}...")
    if len(articles) > 5:
        print(f"\n  ... and {len(articles) - 5} more articles.")


# ── RSS Fetchers ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_google_ai_fetch():
    """Google AI Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import GoogleAIFetcher
    articles = await GoogleAIFetcher().fetch()
    _print_articles("google_ai_blog", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "Google AI Blog returned 0 articles - check feed URL"


@pytest.mark.asyncio
async def test_deepmind_fetch():
    """DeepMind Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import DeepMindFetcher
    articles = await DeepMindFetcher().fetch()
    _print_articles("deepmind_blog", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "DeepMind RSS returned 0 articles"


@pytest.mark.asyncio
async def test_anthropic_fetch():
    """Anthropic News (RSS)."""
    from app.services.news_fetchers.rss_fetcher import AnthropicFetcher
    articles = await AnthropicFetcher().fetch()
    _print_articles("anthropic_news", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "Anthropic RSS returned 0 articles"


@pytest.mark.asyncio
async def test_huggingface_fetch():
    """Hugging Face Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import HuggingFaceFetcher
    articles = await HuggingFaceFetcher().fetch()
    _print_articles("huggingface_blog", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "HuggingFace RSS returned 0 articles"


@pytest.mark.asyncio
async def test_mistral_fetch():
    """Mistral AI News (RSS)."""
    from app.services.news_fetchers.rss_fetcher import MistralFetcher
    articles = await MistralFetcher().fetch()
    _print_articles("mistral_news", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_microsoft_ai_fetch():
    """Microsoft AI Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import MicrosoftAIFetcher
    articles = await MicrosoftAIFetcher().fetch()
    _print_articles("microsoft_ai_blog", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "Microsoft AI Blog returned 0 articles"


@pytest.mark.asyncio
async def test_meta_ai_fetch():
    """Meta AI Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import MetaAIFetcher
    articles = await MetaAIFetcher().fetch()
    _print_articles("meta_ai_blog", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_nvidia_fetch():
    """NVIDIA AI Blog (RSS)."""
    from app.services.news_fetchers.rss_fetcher import NVIDIAFetcher
    articles = await NVIDIAFetcher().fetch()
    _print_articles("nvidia_ai_blog", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "NVIDIA AI Blog returned 0 articles"


@pytest.mark.asyncio
async def test_techcrunch_fetch():
    """TechCrunch AI (RSS)."""
    from app.services.news_fetchers.rss_fetcher import TechCrunchAIFetcher
    articles = await TechCrunchAIFetcher().fetch()
    _print_articles("techcrunch_ai", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "TechCrunch AI returned 0 articles"


@pytest.mark.asyncio
async def test_venturebeat_fetch():
    """VentureBeat AI (RSS)."""
    from app.services.news_fetchers.rss_fetcher import VentureBeatAIFetcher
    articles = await VentureBeatAIFetcher().fetch()
    _print_articles("venturebeat_ai", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "VentureBeat AI returned 0 articles"


@pytest.mark.asyncio
async def test_mit_tech_review_fetch():
    """MIT Technology Review (RSS)."""
    from app.services.news_fetchers.rss_fetcher import MITTechReviewFetcher
    articles = await MITTechReviewFetcher().fetch()
    _print_articles("mit_tech_review", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "MIT Tech Review returned 0 articles"


@pytest.mark.asyncio
async def test_reuters_fetch():
    """Reuters Technology (RSS)."""
    from app.services.news_fetchers.rss_fetcher import ReutersAIFetcher
    articles = await ReutersAIFetcher().fetch()
    _print_articles("reuters_technology", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


# ── Scraper Fetchers ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_fetch():
    """OpenAI Blog (RSS then scrape fallback)."""
    from app.services.news_fetchers.scrapers import OpenAIFetcher
    articles = await OpenAIFetcher().fetch()
    _print_articles("openai_blog", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_google_news_fetch():
    """Google News AI (RSS search)."""
    from app.services.news_fetchers.scrapers import GoogleNewsFetcher
    articles = await GoogleNewsFetcher().fetch()
    _print_articles("google_news_ai", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "Google News returned 0 articles"


@pytest.mark.asyncio
async def test_github_trending_fetch():
    """GitHub Trending AI repos (scraper)."""
    from app.services.news_fetchers.scrapers import GitHubTrendingFetcher
    articles = await GitHubTrendingFetcher().fetch()
    _print_articles("github_trending_ai", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} AI repos found)")


@pytest.mark.asyncio
async def test_xai_fetch():
    """xAI Blog (scraper)."""
    from app.services.news_fetchers.scrapers import XAIFetcher
    articles = await XAIFetcher().fetch()
    _print_articles("xai_news", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_perplexity_fetch():
    """Perplexity AI Blog (scraper)."""
    from app.services.news_fetchers.scrapers import PerplexityFetcher
    articles = await PerplexityFetcher().fetch()
    _print_articles("perplexity_blog", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_producthunt_fetch():
    """Product Hunt AI launches (RSS)."""
    from app.services.news_fetchers.scrapers import ProductHuntAIFetcher
    articles = await ProductHuntAIFetcher().fetch()
    _print_articles("producthunt_ai", articles)
    assert isinstance(articles, list)
    print(f"  Fetcher ran OK ({len(articles)} articles)")


@pytest.mark.asyncio
async def test_arxiv_fetch():
    """ArXiv AI papers fetcher."""
    from app.services.news_fetchers.arxiv_fetcher import ArXivFetcher
    articles = await ArXivFetcher().fetch()
    _print_articles("arxiv_ai", articles)
    assert isinstance(articles, list)
    assert len(articles) > 0, "ArXiv returned 0 papers"


# ── Full Orchestrator (All Sources Combined) ──────────────────────────────────

@pytest.mark.asyncio
async def test_full_orchestrator():
    """
    Runs ALL fetchers via the orchestrator (same path as the scheduler job).
    Prints a summary table of how many articles each source returned.

    NOTE: Makes ~19 concurrent network requests - may take 10-30 seconds.
    """
    from app.services.news_fetchers.orchestrator import NewsFetchOrchestrator

    print("\n" + "="*60)
    print("  FULL ORCHESTRATOR TEST - all 19 sources")
    print("="*60)

    orchestrator = NewsFetchOrchestrator()
    articles = await orchestrator.fetch_all()

    print(f"\n  TOTAL articles fetched (after URL dedup): {len(articles)}")

    # Group by source
    by_source: dict[str, int] = {}
    for a in articles:
        by_source[a.source_name] = by_source.get(a.source_name, 0) + 1

    print("\n  Per-source breakdown:")
    for source, count in sorted(by_source.items()):
        status = "OK " if count > 0 else "FAIL"
        print(f"    [{status}] {source:<35} {count:>3} articles")

    assert len(articles) > 0, (
        "Orchestrator returned 0 articles! All fetchers may be failing. "
        "Run individual fetcher tests to identify the broken ones."
    )


# ── Run directly: python test_news_fetch.py ───────────────────────────────────

if __name__ == "__main__":
    """
    Run this file directly to fetch and print ALL news from all 19 sources.

    Usage (from backend/ directory):
        python tests/test_news_fetch.py

    Or from inside the tests/ directory:
        cd tests
        python test_news_fetch.py
    """
    import asyncio
    import sys

    # Fix Windows terminal encoding — prevents crash on emoji/special chars
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def safe(text: str, max_len: int = 120) -> str:
        """Safely truncate and encode text for Windows terminal."""
        return text[:max_len].encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    async def main():
        import os

        # ── Fix paths so imports work from any directory ──────────────────────
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        # ── Load .env from backend/ directory explicitly ──────────────────────
        # This fixes the "9 validation errors for Settings" crash when running
        # from backend/tests/ instead of backend/
        env_file = os.path.join(backend_dir, ".env")
        if os.path.exists(env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file, override=False)
                print(f"  [.env loaded from: {env_file}]")
            except ImportError:
                # dotenv not installed — manually parse the .env file
                with open(env_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, val = line.partition("=")
                            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
                print(f"  [.env parsed manually from: {env_file}]")
        else:
            print(f"  [WARNING] No .env found at {env_file}")

        os.environ.setdefault("APP_ENV", "testing")

        from app.services.news_fetchers.orchestrator import NewsFetchOrchestrator

        print("\n" + "#" * 65)
        print("#   AI PULSE — LIVE NEWS FETCH TEST")
        print("#   Fetching from all 19 sources... please wait (10-30s)")
        print("#" * 65)

        orchestrator = NewsFetchOrchestrator()
        articles = await orchestrator.fetch_all()

        # ── Filter to recent articles only ────────────────────────────────
        from datetime import datetime, timezone, timedelta
        DAYS_RECENT = 3   # ← change this to see more/fewer days
        cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_RECENT)

        recent = []
        no_date = []
        old = []
        for a in articles:
            if a.published_at is None:
                no_date.append(a)   # no date = keep it (can't know)
            elif a.published_at >= cutoff:
                recent.append(a)
            else:
                old.append(a)

        # Sort recent by newest first
        recent.sort(key=lambda a: a.published_at, reverse=True)
        display = recent + no_date   # show recent then undated

        # ── Per-source summary ────────────────────────────────────────────
        by_source: dict[str, list] = {}
        for a in recent:
            by_source.setdefault(a.source_name, []).append(a)

        print(f"\n{'='*65}")
        print(f"  TOTAL FETCHED : {len(articles)} articles from all sources")
        print(f"  RECENT ({DAYS_RECENT} days): {len(recent)} articles  |  OLD (skipped): {len(old)}  |  NO DATE: {len(no_date)}")
        print(f"{'='*65}")
        for source, arts in sorted(by_source.items()):
            status = "OK  " if arts else "----"
            print(f"  [{status}] {source:<35}  {len(arts):>3} recent articles")

        # ── Print only recent articles ────────────────────────────────────
        print(f"\n\n{'#'*65}")
        print(f"#   RECENT ARTICLES — Last {DAYS_RECENT} days ({len(display)} shown)")
        print(f"{'#'*65}")

        for i, a in enumerate(display, 1):
            print(f"\n[{i:>3}] {safe(a.title, 100)}")
            print(f"       Source  : {a.source_name}")
            print(f"       URL     : {safe(a.url, 100)}")
            if a.published_at:
                print(f"       Date    : {a.published_at.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                print(f"       Date    : (no date)")
            if a.description:
                print(f"       Summary : {safe(str(a.description), 120)}...")
            if a.is_official:
                print(f"       Official: {a.official_company}")

        print(f"\n{'='*65}")
        print(f"  DONE — Showing {len(display)} recent articles (last {DAYS_RECENT} days)")
        print(f"  Total fetched from all sources: {len(articles)}")
        print(f"  Tip: change DAYS_RECENT in the script to see more/fewer days")
        print(f"{'='*65}\n")

    asyncio.run(main())
