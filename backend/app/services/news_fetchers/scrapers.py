"""
AI Pulse – OpenAI Blog Fetcher
================================
Fetches news from OpenAI's official blog.
Uses RSS feed with HTML scraping fallback.
"""

from __future__ import annotations

from typing import ClassVar

from bs4 import BeautifulSoup

from app.services.news_fetchers.base import BaseFetcher, RawArticle
from app.services.news_fetchers.rss_fetcher import RSSFetcher
from app.utils.date_utils import parse_datetime
from app.utils.http_client import fetch_text
from app.utils.text_utils import clean_html


class OpenAIFetcher(BaseFetcher):
    """
    Fetches articles from OpenAI's blog and newsroom.
    Tries RSS first, falls back to HTML scraping.
    """

    SOURCE_NAME: ClassVar[str] = "openai_blog"
    SOURCE_DOMAIN: ClassVar[str] = "openai.com"
    SOURCE_TYPE: ClassVar[str] = "rss"
    IS_OFFICIAL: ClassVar[bool] = True
    OFFICIAL_COMPANY: ClassVar[str] = "OpenAI"

    RSS_URL = "https://openai.com/blog/rss.xml"
    BLOG_URL = "https://openai.com/news/"

    async def fetch(self) -> list[RawArticle]:
        """Try RSS first, fall back to HTML scraping."""
        articles = await self._fetch_rss()
        if articles:
            return articles

        self.logger.info("openai_rss_empty_trying_scrape")
        return await self._fetch_scrape()

    async def _fetch_rss(self) -> list[RawArticle]:
        """Attempt to fetch via RSS feed."""
        fetcher = RSSFetcher(
            feed_url=self.RSS_URL,
            source_name=self.SOURCE_NAME,
            source_domain=self.SOURCE_DOMAIN,
            is_official=self.IS_OFFICIAL,
            official_company=self.OFFICIAL_COMPANY,
        )
        return await fetcher.fetch()

    async def _fetch_scrape(self) -> list[RawArticle]:
        """Scrape OpenAI news page as fallback."""
        articles: list[RawArticle] = []
        try:
            html = await fetch_text(self.BLOG_URL, source_name=self.SOURCE_NAME)
            soup = BeautifulSoup(html, "lxml")

            # OpenAI news items are in article cards
            for card in soup.find_all("a", href=True):
                href = card.get("href", "")
                if not href.startswith("/news/") and not href.startswith("https://openai.com/news/"):
                    continue

                title_el = card.find(["h2", "h3", "h4"])
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if len(title) < 10:
                    continue

                url = href if href.startswith("http") else f"https://openai.com{href}"

                # Try to get date
                time_el = card.find("time")
                published_at = None
                if time_el:
                    published_at = parse_datetime(time_el.get("datetime") or time_el.get_text())

                # Description
                desc_el = card.find("p")
                description = desc_el.get_text(strip=True) if desc_el else None

                article = self._make_article(
                    title=title,
                    url=url,
                    description=description,
                    published_at=published_at,
                )
                articles.append(article)

        except Exception as exc:
            self.logger.error("openai_scrape_error", error=str(exc))

        return articles


class GoogleNewsFetcher(BaseFetcher):
    """
    Fetches AI news from Google News RSS.
    Uses the Google News RSS endpoint with AI-focused search queries.
    """

    SOURCE_NAME: ClassVar[str] = "google_news_ai"
    SOURCE_DOMAIN: ClassVar[str] = "news.google.com"
    SOURCE_TYPE: ClassVar[str] = "rss"

    QUERIES = [
        "artificial intelligence",
        "large language model",
        "AI model release",
    ]

    async def fetch(self) -> list[RawArticle]:
        """Fetch from multiple Google News queries and merge."""
        from app.services.news_fetchers.rss_fetcher import RSSFetcher
        import asyncio
        from urllib.parse import quote

        tasks = []
        for query in self.QUERIES:
            encoded = quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            fetcher = RSSFetcher(
                feed_url=feed_url,
                source_name=self.SOURCE_NAME,
                source_domain=self.SOURCE_DOMAIN,
            )
            tasks.append(fetcher.fetch())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                self.logger.warning("google_news_fetch_error", error=str(result))
                continue
            for article in result:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    articles.append(article)

        return articles


class GitHubTrendingFetcher(BaseFetcher):
    """
    Scrapes GitHub Trending for AI/ML repositories.
    Converts trending repos into news-like articles.
    """

    SOURCE_NAME: ClassVar[str] = "github_trending_ai"
    SOURCE_DOMAIN: ClassVar[str] = "github.com"
    SOURCE_TYPE: ClassVar[str] = "scrape"

    TRENDING_URLS = [
        "https://github.com/trending/python?since=daily&spoken_language_code=en",
        "https://github.com/trending?since=daily&spoken_language_code=en",
    ]

    AI_KEYWORDS = {
        "llm", "ai", "ml", "machine-learning", "deep-learning", "neural",
        "transformer", "diffusion", "language-model", "chatbot", "gpt",
        "llama", "stable-diffusion", "generative", "embedding", "rag",
        "agent", "multimodal", "vision", "nlp", "reinforcement-learning",
    }

    async def fetch(self) -> list[RawArticle]:
        """Scrape GitHub trending and filter AI/ML repos."""
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for url in self.TRENDING_URLS:
            try:
                html = await fetch_text(url, source_name=self.SOURCE_NAME)
                repos = self._parse_trending(html)
                for repo in repos:
                    if repo.url not in seen:
                        seen.add(repo.url)
                        articles.append(repo)
            except Exception as exc:
                self.logger.warning("github_trending_fetch_error", url=url, error=str(exc))

        return articles

    def _parse_trending(self, html: str) -> list[RawArticle]:
        """Parse GitHub trending page HTML."""
        articles: list[RawArticle] = []
        soup = BeautifulSoup(html, "lxml")

        for article_el in soup.find_all("article", class_="Box-row"):
            try:
                # Repo name
                h2 = article_el.find("h2")
                if not h2:
                    continue

                link = h2.find("a")
                if not link:
                    continue

                repo_path = link.get("href", "").strip("/")
                if not repo_path or "/" not in repo_path:
                    continue

                repo_url = f"https://github.com/{repo_path}"
                repo_name = repo_path.replace("/", " / ")

                # Description
                desc_el = article_el.find("p")
                description = desc_el.get_text(strip=True) if desc_el else ""

                # Stars gained today
                stars_el = article_el.find("span", class_=lambda c: c and "d-inline-block" in c)
                stars_text = ""
                for span in article_el.find_all("span"):
                    text = span.get_text(strip=True)
                    if "stars today" in text.lower():
                        stars_text = text
                        break

                # Filter: only include if AI-related
                combined_text = f"{repo_name} {description}".lower()
                topics = [a.get("href", "").split("/")[-1] for a in article_el.find_all("a", href=lambda h: h and "/topics/" in h)]

                is_ai = any(kw in combined_text for kw in self.AI_KEYWORDS)
                is_ai = is_ai or any(kw in t.lower() for t in topics for kw in self.AI_KEYWORDS)

                if not is_ai:
                    continue

                title = f"🔥 GitHub Trending: {repo_name}"
                if stars_text:
                    title += f" ({stars_text})"

                article = self._make_article(
                    title=title,
                    url=repo_url,
                    description=description or None,
                )
                articles.append(article)

            except Exception as exc:
                self.logger.debug("github_repo_parse_error", error=str(exc))
                continue

        return articles


from bs4 import BeautifulSoup  # noqa: E402 — needed for GitHubTrendingFetcher


class XAIFetcher(BaseFetcher):
    """Scrapes xAI (x.ai) news/blog — no RSS available."""

    SOURCE_NAME: ClassVar[str] = "xai_news"
    SOURCE_DOMAIN: ClassVar[str] = "x.ai"
    SOURCE_TYPE: ClassVar[str] = "scrape"
    IS_OFFICIAL: ClassVar[bool] = True
    OFFICIAL_COMPANY: ClassVar[str] = "xAI"

    BLOG_URL = "https://x.ai/blog"

    async def fetch(self) -> list[RawArticle]:
        articles: list[RawArticle] = []
        try:
            html = await fetch_text(self.BLOG_URL, source_name=self.SOURCE_NAME)
            soup = BeautifulSoup(html, "lxml")

            for card in soup.find_all("a", href=True):
                href = card.get("href", "")
                if not href.startswith("/blog/") and "x.ai/blog/" not in href:
                    continue

                title_el = card.find(["h2", "h3", "h4", "strong"])
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if len(title) < 10:
                    continue

                url = href if href.startswith("http") else f"https://x.ai{href}"
                article = self._make_article(title=title, url=url)
                articles.append(article)

        except Exception as exc:
            self.logger.error("xai_scrape_error", error=str(exc))

        return articles


class PerplexityFetcher(BaseFetcher):
    """Scrapes Perplexity AI blog — no RSS available."""

    SOURCE_NAME: ClassVar[str] = "perplexity_blog"
    SOURCE_DOMAIN: ClassVar[str] = "perplexity.ai"
    SOURCE_TYPE: ClassVar[str] = "scrape"
    IS_OFFICIAL: ClassVar[bool] = True
    OFFICIAL_COMPANY: ClassVar[str] = "Perplexity AI"

    BLOG_URL = "https://www.perplexity.ai/hub/blog"

    async def fetch(self) -> list[RawArticle]:
        articles: list[RawArticle] = []
        try:
            html = await fetch_text(self.BLOG_URL, source_name=self.SOURCE_NAME)
            soup = BeautifulSoup(html, "lxml")

            for card in soup.find_all("a", href=True):
                href = card.get("href", "")
                if "/hub/blog/" not in href:
                    continue

                title_el = card.find(["h2", "h3", "h4"])
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if len(title) < 10:
                    continue

                url = href if href.startswith("http") else f"https://www.perplexity.ai{href}"
                article = self._make_article(title=title, url=url)
                articles.append(article)

        except Exception as exc:
            self.logger.error("perplexity_scrape_error", error=str(exc))

        return articles


class ProductHuntAIFetcher(BaseFetcher):
    """
    Fetches AI product launches from Product Hunt.
    Uses Product Hunt's public GraphQL API (no auth required for basic queries).
    """

    SOURCE_NAME: ClassVar[str] = "producthunt_ai"
    SOURCE_DOMAIN: ClassVar[str] = "producthunt.com"
    SOURCE_TYPE: ClassVar[str] = "api"

    PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"
    PH_RSS_FALLBACK = "https://www.producthunt.com/feed?category=artificial-intelligence"

    async def fetch(self) -> list[RawArticle]:
        """Try GraphQL API first, fall back to RSS."""
        articles = await self._fetch_rss_fallback()
        return articles

    async def _fetch_rss_fallback(self) -> list[RawArticle]:
        """Fetch AI launches from Product Hunt RSS."""
        from app.services.news_fetchers.rss_fetcher import RSSFetcher

        fetcher = RSSFetcher(
            feed_url=self.PH_RSS_FALLBACK,
            source_name=self.SOURCE_NAME,
            source_domain=self.SOURCE_DOMAIN,
        )
        return await fetcher.fetch()
