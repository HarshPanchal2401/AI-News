"""
AI Pulse – Text Utilities
==========================
String normalization, cleaning, and similarity helpers.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


# ── URL Normalization ─────────────────────────────────────────────────────────

# Query parameters to strip (tracking / analytics)
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "ref", "referrer", "source", "campaign", "fbclid", "gclid",
    "mc_cid", "mc_eid", "_ga", "yclid", "msclkid",
}


def normalize_url(url: str) -> str:
    """
    Canonicalize a URL by:
    - Lowercasing scheme and host
    - Removing tracking query parameters
    - Removing trailing slashes from path
    - Removing URL fragments (#)
    """
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        # Filter tracking params
        query_params = {
            k: v
            for k, v in parse_qs(parsed.query).items()
            if k.lower() not in _STRIP_PARAMS
        }
        query = urlencode(query_params, doseq=True)
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url.strip().lower()


# ── Title Normalization ───────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """
    Normalize an article title for duplicate detection.
    - Unicode normalize (NFC)
    - Lowercase
    - Remove punctuation and special characters
    - Collapse whitespace
    - Strip leading/trailing whitespace
    """
    if not title:
        return ""
    # Unicode normalization
    text = unicodedata.normalize("NFC", title)
    # Lowercase
    text = text.lower()
    # Remove punctuation except spaces
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_fingerprint(title: str) -> str:
    """Return a SHA-256 fingerprint of a normalized title."""
    normalized = normalize_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Content Hashing ───────────────────────────────────────────────────────────

def content_fingerprint(title: str, body_snippet: str = "") -> str:
    """
    Generate a SHA-256 fingerprint from the normalized title + first 200 chars of body.
    Used for exact-duplicate detection.
    """
    normalized_title = normalize_title(title)
    normalized_body = body_snippet[:200].lower().strip() if body_snippet else ""
    combined = f"{normalized_title}||{normalized_body}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


# ── Text Cleaning ─────────────────────────────────────────────────────────────

def clean_html(html_text: str) -> str:
    """Strip HTML tags from text."""
    text = re.sub(r"<[^>]+>", " ", html_text or "")
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate_text(text: str, max_length: int = 500) -> str:
    """Truncate text to max_length characters, ending at a word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.8:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:") + "…"


def estimate_reading_time(text: str, wpm: int = 238) -> int:
    """
    Estimate reading time in minutes based on average words per minute.

    Args:
        text: Article text content.
        wpm: Words per minute (average adult reader: 238 wpm).

    Returns:
        Reading time in minutes (minimum 1).
    """
    word_count = len(text.split())
    minutes = max(1, round(word_count / wpm))
    return minutes


# ── Entity Fingerprinting ─────────────────────────────────────────────────────

def entity_fingerprint(companies: list[str], product: str = "", event_type: str = "") -> str:
    """
    Create a fingerprint from company + product + event for semantic deduplication.
    Example: "openai|gpt-6|launch"
    """
    normalized_companies = sorted(c.lower().strip() for c in companies if c)
    parts = [
        "|".join(normalized_companies),
        product.lower().strip(),
        event_type.lower().strip(),
    ]
    combined = "::".join(p for p in parts if p)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest() if combined else ""


# ── Source Domain Extraction ──────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    """Extract the root domain from a URL (e.g., 'techcrunch.com')."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        # Remove 'www.' prefix
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text
