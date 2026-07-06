"""
AI Pulse – Async HTTP Client
==============================
Shared httpx AsyncClient with retry logic, timeout, and user-agent rotation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import FetchError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Realistic browser user agents to avoid bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_ua_index = 0


def _get_user_agent() -> str:
    """Rotate through user agents to distribute requests."""
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


def build_http_client(
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """
    Build a configured AsyncClient with sensible defaults.

    Args:
        timeout: Request timeout in seconds (defaults to settings value).
        headers: Additional headers to include.
        follow_redirects: Whether to follow redirects.

    Returns:
        Configured httpx.AsyncClient instance.
    """
    default_headers = {
        "User-Agent": _get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    if headers:
        default_headers.update(headers)

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout or settings.fetch_timeout_seconds),
        headers=default_headers,
        follow_redirects=follow_redirects,
        http2=True,
    )


async def fetch_with_retry(
    url: str,
    source_name: str = "unknown",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    max_retries: int | None = None,
) -> httpx.Response:
    """
    Fetch a URL with exponential backoff retry.

    Args:
        url: Target URL.
        source_name: Source name for error messages.
        method: HTTP method.
        headers: Extra headers.
        params: Query parameters.
        json_body: JSON request body (for POST).
        max_retries: Override for max retry attempts.

    Returns:
        httpx.Response object.

    Raises:
        FetchError: If all retries are exhausted or a non-retryable error occurs.
    """
    retries = max_retries or settings.fetch_max_retries

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(retries),
        wait=wait_exponential(
            multiplier=settings.fetch_retry_delay_seconds, min=1, max=30
        ),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
        ),
        reraise=False,
    ):
        with attempt:
            try:
                async with build_http_client(headers=headers) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_body,
                    )
                    response.raise_for_status()
                    logger.debug(
                        "fetch_success",
                        source=source_name,
                        url=url,
                        status=response.status_code,
                    )
                    return response
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "fetch_http_error",
                    source=source_name,
                    url=url,
                    status=exc.response.status_code,
                )
                # Don't retry 4xx errors (except 429 Too Many Requests)
                if exc.response.status_code == 429:
                    retry_after = int(
                        exc.response.headers.get("Retry-After", "5")
                    )
                    logger.info("rate_limited", source=source_name, wait=retry_after)
                    await asyncio.sleep(retry_after)
                    raise  # Trigger retry
                if 400 <= exc.response.status_code < 500:
                    raise FetchError(source_name, f"HTTP {exc.response.status_code}: {url}")
                raise  # 5xx: trigger retry

    raise FetchError(source_name, f"All {retries} retries exhausted for {url}")


async def fetch_json(
    url: str,
    source_name: str = "unknown",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    """Convenience wrapper that fetches and JSON-decodes a response."""
    response = await fetch_with_retry(url, source_name, headers=headers, params=params)
    return response.json()


async def fetch_text(
    url: str,
    source_name: str = "unknown",
    headers: dict[str, str] | None = None,
) -> str:
    """Convenience wrapper that fetches and returns response text."""
    response = await fetch_with_retry(url, source_name, headers=headers)
    return response.text


async def scrape_article_text(url: str) -> str:
    """
    Scrape the full body content of an article URL, cleaning HTML boilerplate.
    Returns parsed plain text.
    """
    from bs4 import BeautifulSoup
    try:
        response = await fetch_with_retry(url, source_name="scraper", max_retries=1)
        if response.status_code != 200:
            return ""
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Clean soup
        for element in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]):
            element.decompose()
            
        # Extract paragraph tags
        paragraphs = soup.find_all("p")
        text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30])
        
        # Limit text length to 10,000 characters
        return text[:10000]
    except Exception as exc:
        logger.warning("scrape_article_text_failed", url=url, error=str(exc))
        return ""
