"""
AI News Intelligence Engine – Community Source Fetchers
==========================================================
Fetchers for community-driven AI news sources:
  - Reddit (r/artificial + r/MachineLearning + r/LocalLLaMA)
  - Hacker News (Algolia API, AI-tagged stories)
  - GitHub Releases (top AI repos: llama.cpp, ollama, vllm, etc.)
"""

from __future__ import annotations

import asyncio
from typing import ClassVar
from urllib.parse import quote

from app.core.logging import get_logger
from app.services.news_fetchers.base import BaseFetcher, RawArticle
from app.utils.http_client import fetch_json
from app.utils.date_utils import parse_datetime

logger = get_logger(__name__)


# ── Reddit AI Fetcher ─────────────────────────────────────────────────────────

class RedditAIFetcher(BaseFetcher):
    """
    Fetches hot posts from AI-focused Reddit communities.
    Uses the public Reddit JSON API — no OAuth required.
    Subreddits: r/artificial, r/MachineLearning, r/LocalLLaMA, r/singularity.
    """

    SOURCE_NAME: ClassVar[str] = "reddit_ai"
    SOURCE_DOMAIN: ClassVar[str] = "reddit.com"
    SOURCE_TYPE: ClassVar[str] = "api"

    SUBREDDITS = [
        "artificial",
        "MachineLearning",
        "LocalLLaMA",
        "singularity",
    ]

    # Minimum upvotes to consider an article
    MIN_UPVOTES = 50

    # Domains that represent real news (not memes/discussions)
    NEWS_DOMAINS = {
        "openai.com", "anthropic.com", "deepmind.google", "ai.meta.com",
        "techcrunch.com", "venturebeat.com", "technologyreview.com",
        "arxiv.org", "wired.com", "theverge.com", "arstechnica.com",
        "reuters.com", "bloomberg.com", "huggingface.co", "mistral.ai",
        "github.com", "nature.com", "science.org",
    }

    async def fetch(self) -> list[RawArticle]:
        """Fetch from all subreddits concurrently."""
        tasks = [self._fetch_subreddit(sub) for sub in self.SUBREDDITS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                self.logger.warning("reddit_subreddit_error", error=str(result))
                continue
            for article in result:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    articles.append(article)

        return articles

    async def _fetch_subreddit(self, subreddit: str) -> list[RawArticle]:
        """Fetch hot posts from a single subreddit."""
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25"
        articles: list[RawArticle] = []

        try:
            data = await fetch_json(
                url,
                source_name=self.SOURCE_NAME,
                headers={"User-Agent": "AINewsBot/2.0 (news aggregator)"},
            )
            posts = data.get("data", {}).get("children", [])

            for post_wrapper in posts:
                post = post_wrapper.get("data", {})
                if post.get("is_self"):
                    # Skip text-only posts (no external link)
                    continue

                link_url: str = post.get("url", "")
                domain: str = post.get("domain", "")
                score: int = post.get("score", 0)
                title: str = post.get("title", "").strip()

                if not title or not link_url or score < self.MIN_UPVOTES:
                    continue

                # Only include posts linking to real news sources
                is_news = any(nd in domain for nd in self.NEWS_DOMAINS)
                if not is_news:
                    continue

                created_utc = post.get("created_utc")
                published_at = None
                if created_utc:
                    from datetime import datetime, timezone
                    published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

                description = (
                    f"Reddit r/{subreddit} — {score} upvotes, "
                    f"{post.get('num_comments', 0)} comments"
                )

                article = self._make_article(
                    title=title,
                    url=link_url,
                    description=description,
                    published_at=published_at,
                )
                articles.append(article)

        except Exception as exc:
            self.logger.error("reddit_fetch_error", subreddit=subreddit, error=str(exc))

        return articles


# ── Hacker News Fetcher ───────────────────────────────────────────────────────

class HackerNewsFetcher(BaseFetcher):
    """
    Fetches top AI-related stories from Hacker News via Algolia API.
    Filters for stories tagged with 'ai' or with AI-related keywords in title.
    """

    SOURCE_NAME: ClassVar[str] = "hacker_news"
    SOURCE_DOMAIN: ClassVar[str] = "news.ycombinator.com"
    SOURCE_TYPE: ClassVar[str] = "api"

    ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"

    AI_QUERIES = [
        "artificial intelligence",
        "large language model",
        "machine learning",
        "OpenAI OR Anthropic OR DeepMind OR Google AI",
    ]

    MIN_POINTS = 30

    async def fetch(self) -> list[RawArticle]:
        """Fetch AI stories from HN Algolia search API."""
        tasks = [self._fetch_query(q) for q in self.AI_QUERIES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[RawArticle] = []
        seen_ids: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                self.logger.warning("hn_query_error", error=str(result))
                continue
            for article in result:
                story_id = article.url.split("id=")[-1] if "id=" in article.url else article.url
                if story_id not in seen_ids:
                    seen_ids.add(story_id)
                    articles.append(article)

        return articles

    async def _fetch_query(self, query: str) -> list[RawArticle]:
        """Fetch stories for a single search query."""
        from datetime import datetime, timezone, timedelta

        # Only look at stories from the last 24 hours
        cutoff = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())

        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"points>={self.MIN_POINTS},created_at_i>={cutoff}",
            "hitsPerPage": 20,
        }
        query_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        url = f"{self.ALGOLIA_URL}?{query_str}"

        articles: list[RawArticle] = []

        try:
            data = await fetch_json(url, source_name=self.SOURCE_NAME)
            hits = data.get("hits", [])

            for hit in hits:
                title: str = hit.get("title", "").strip()
                story_url: str = hit.get("url", "")
                points: int = hit.get("points", 0)
                story_id: str = str(hit.get("objectID", ""))
                created_at_i = hit.get("created_at_i")

                if not title:
                    continue

                # If no external URL, link to the HN discussion
                if not story_url:
                    story_url = f"https://news.ycombinator.com/item?id={story_id}"

                published_at = None
                if created_at_i:
                    from datetime import datetime, timezone
                    published_at = datetime.fromtimestamp(created_at_i, tz=timezone.utc)

                description = (
                    f"Hacker News — {points} points, "
                    f"{hit.get('num_comments', 0)} comments"
                )

                article = self._make_article(
                    title=title,
                    url=story_url,
                    description=description,
                    published_at=published_at,
                )
                articles.append(article)

        except Exception as exc:
            self.logger.error("hn_fetch_error", query=query, error=str(exc))

        return articles


# ── GitHub Releases Fetcher ───────────────────────────────────────────────────

class GitHubReleasesFetcher(BaseFetcher):
    """
    Fetches latest releases from key AI/ML GitHub repositories.
    Uses the public GitHub REST API (no auth for public repos).
    """

    SOURCE_NAME: ClassVar[str] = "github_releases_ai"
    SOURCE_DOMAIN: ClassVar[str] = "github.com"
    SOURCE_TYPE: ClassVar[str] = "api"

    # Top AI repos to monitor for new releases
    MONITORED_REPOS = [
        "ggerganov/llama.cpp",
        "ollama/ollama",
        "vllm-project/vllm",
        "huggingface/transformers",
        "openai/openai-python",
        "anthropics/anthropic-sdk-python",
        "langchain-ai/langchain",
        "run-llama/llama_index",
        "BerriAI/litellm",
        "pytorch/pytorch",
        "microsoft/autogen",
        "ComfyUI/ComfyUI",
        "AUTOMATIC1111/stable-diffusion-webui",
        "openai/whisper",
        "facebookresearch/segment-anything",
    ]

    async def fetch(self) -> list[RawArticle]:
        """Fetch latest release from all monitored repos concurrently."""
        # Limit concurrency to avoid GitHub rate limiting
        semaphore = asyncio.Semaphore(5)

        async def fetch_with_limit(repo: str) -> list[RawArticle]:
            async with semaphore:
                return await self._fetch_repo_release(repo)

        tasks = [fetch_with_limit(repo) for repo in self.MONITORED_REPOS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[RawArticle] = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.debug("github_release_error", error=str(result))
                continue
            articles.extend(result)

        return articles

    async def _fetch_repo_release(self, repo: str) -> list[RawArticle]:
        """Fetch the latest release for a single repository."""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        articles: list[RawArticle] = []

        try:
            data = await fetch_json(
                url,
                source_name=self.SOURCE_NAME,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "AINewsBot/2.0",
                },
            )

            tag_name: str = data.get("tag_name", "")
            name: str = data.get("name", "") or tag_name
            html_url: str = data.get("html_url", "")
            body: str = (data.get("body", "") or "")[:400]
            published_at_str: str = data.get("published_at", "")
            is_prerelease: bool = data.get("prerelease", False)

            if not html_url or not name or is_prerelease:
                return []

            published_at = parse_datetime(published_at_str) if published_at_str else None

            # Only report releases from the last 7 days
            if published_at:
                from app.utils.date_utils import hours_since
                if hours_since(published_at) > 168:  # 7 days
                    return []

            repo_name = repo.split("/")[-1]
            title = f"🚀 {repo_name} {name} released"

            article = self._make_article(
                title=title,
                url=html_url,
                description=body.strip() if body.strip() else f"New release of {repo}",
                published_at=published_at,
            )
            articles.append(article)

        except Exception as exc:
            # 404 = no release yet, 403 = rate limited — both are expected
            self.logger.debug(
                "github_release_fetch_error", repo=repo, error=str(exc)
            )

        return articles
