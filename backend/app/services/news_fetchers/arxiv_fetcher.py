"""
AI Pulse – arXiv Fetcher
==========================
Fetches latest AI/ML research papers from arXiv API.
Queries cs.AI, cs.LG, cs.CL categories for the past 24 hours.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import timezone
from typing import ClassVar

from app.core.config import settings
from app.services.news_fetchers.base import BaseFetcher, RawArticle
from app.utils.date_utils import hours_ago, parse_datetime
from app.utils.http_client import fetch_text


class ArXivFetcher(BaseFetcher):
    """
    Fetches recent AI research papers from arXiv.
    Uses the arXiv Atom API — no API key required.
    """

    SOURCE_NAME: ClassVar[str] = "arxiv"
    SOURCE_DOMAIN: ClassVar[str] = "arxiv.org"
    SOURCE_TYPE: ClassVar[str] = "api"
    IS_OFFICIAL: ClassVar[bool] = False

    ARXIV_API_URL = "https://export.arxiv.org/api/query"
    ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO"]
    ARXIV_NS = "http://www.w3.org/2005/Atom"

    async def fetch(self) -> list[RawArticle]:
        """Fetch recent AI papers from arXiv and return as RawArticles."""
        category_query = " OR ".join(f"cat:{c}" for c in self.ARXIV_CATEGORIES)
        params = {
            "search_query": category_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": settings.max_articles_per_source,
        }

        # Build URL with query params
        from urllib.parse import urlencode
        url = f"{self.ARXIV_API_URL}?{urlencode(params)}"

        xml_text = await fetch_text(url, source_name=self.SOURCE_NAME)
        return self._parse_feed(xml_text)

    def _parse_feed(self, xml_text: str) -> list[RawArticle]:
        """Parse arXiv Atom XML feed into RawArticles."""
        articles: list[RawArticle] = []
        cutoff = hours_ago(48)  # Only last 48h

        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": self.ARXIV_NS}

            for entry in root.findall("atom:entry", ns):
                # Skip opensearch metadata entries
                title_el = entry.find("atom:title", ns)
                id_el = entry.find("atom:id", ns)

                if title_el is None or id_el is None:
                    continue

                title = title_el.text.strip().replace("\n", " ") if title_el.text else ""
                arxiv_id = id_el.text.strip() if id_el.text else ""

                # Convert arXiv abstract URL to standard format
                url = arxiv_id.replace("http://", "https://")

                # Abstract/description
                abstract_el = entry.find("atom:summary", ns)
                description = (abstract_el.text or "").strip().replace("\n", " ") if abstract_el is not None else ""

                # Authors
                authors = []
                for author_el in entry.findall("atom:author", ns):
                    name_el = author_el.find("atom:name", ns)
                    if name_el is not None and name_el.text:
                        authors.append(name_el.text.strip())
                author = ", ".join(authors[:3])
                if len(authors) > 3:
                    author += f" et al."

                # Published date
                published_el = entry.find("atom:published", ns)
                published_at = (
                    parse_datetime(published_el.text) if published_el is not None else None
                )

                # Only include papers from the last 48h
                if published_at and published_at.replace(tzinfo=timezone.utc) < cutoff.replace(tzinfo=timezone.utc):
                    continue

                # PDF link
                pdf_url = None
                for link_el in entry.findall("atom:link", ns):
                    if link_el.get("title") == "pdf":
                        pdf_url = link_el.get("href")
                        break

                article = self._make_article(
                    title=title,
                    url=url,
                    description=description[:1000] if description else None,
                    author=author or None,
                    published_at=published_at,
                )
                articles.append(article)

        except ET.ParseError as exc:
            self.logger.error("arxiv_xml_parse_error", error=str(exc))

        return articles
