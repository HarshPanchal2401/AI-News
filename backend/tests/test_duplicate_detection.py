"""
Tests for the Duplicate Detection Engine.
Covers all 5 detection layers.
"""

from __future__ import annotations

import pytest
from app.services.duplicate_detection.engine import (
    DuplicateDetectionEngine,
    cosine_similarity,
)
from app.utils.text_utils import (
    content_fingerprint,
    entity_fingerprint,
    normalize_title,
    normalize_url,
    title_fingerprint,
)


# ── Unit Tests: Text Utilities ────────────────────────────────────────────────

class TestNormalizeURL:
    def test_strips_utm_params(self):
        url = "https://techcrunch.com/article?utm_source=google&utm_medium=cpc"
        assert "utm_source" not in normalize_url(url)
        assert "utm_medium" not in normalize_url(url)

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/article/") == "https://example.com/article"

    def test_lowercases(self):
        assert normalize_url("HTTPS://EXAMPLE.COM/Article") == "https://example.com/Article"

    def test_strips_fragment(self):
        url = "https://example.com/article#section1"
        assert "#section1" not in normalize_url(url)


class TestNormalizeTitle:
    def test_lowercases(self):
        assert normalize_title("OpenAI Launches GPT-6") == "openai launches gpt 6"

    def test_removes_punctuation(self):
        assert normalize_title("Hello, World!") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize_title("Hello   World") == "hello world"

    def test_handles_empty(self):
        assert normalize_title("") == ""


class TestTitleFingerprint:
    def test_same_title_same_hash(self):
        fp1 = title_fingerprint("OpenAI Launches GPT-6")
        fp2 = title_fingerprint("OpenAI Launches GPT-6")
        assert fp1 == fp2

    def test_different_titles_different_hash(self):
        fp1 = title_fingerprint("OpenAI launches GPT-6")
        fp2 = title_fingerprint("Google releases Gemini 2")
        assert fp1 != fp2

    def test_case_insensitive(self):
        fp1 = title_fingerprint("OpenAI Launches GPT-6")
        fp2 = title_fingerprint("OPENAI LAUNCHES GPT-6")
        assert fp1 == fp2


class TestEntityFingerprint:
    def test_same_entities_same_hash(self):
        fp1 = entity_fingerprint(["OpenAI"], "GPT-6", "launch")
        fp2 = entity_fingerprint(["OpenAI"], "GPT-6", "launch")
        assert fp1 == fp2

    def test_company_order_independent(self):
        fp1 = entity_fingerprint(["OpenAI", "Microsoft"], "GPT-6", "partnership")
        fp2 = entity_fingerprint(["Microsoft", "OpenAI"], "GPT-6", "partnership")
        assert fp1 == fp2

    def test_empty_returns_empty(self):
        assert entity_fingerprint([], "", "") == ""


# ── Unit Tests: Cosine Similarity ─────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert cosine_similarity(v1, v2) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        assert cosine_similarity(v1, v2) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ── Integration Tests: Detection Engine ───────────────────────────────────────

@pytest.mark.asyncio
class TestDuplicateDetectionEngine:
    async def test_no_duplicate_returns_false(self, db, sample_raw_article):
        engine = DuplicateDetectionEngine(db)
        result = await engine.check(sample_raw_article)
        assert result.is_duplicate is False
        assert result.canonical_id is None

    async def test_url_duplicate_detected(self, db, sample_article, sample_raw_article):
        """Same URL should be detected as duplicate."""
        # Modify raw article to have same URL as DB article
        sample_raw_article.url = sample_article.url
        sample_raw_article.normalized_url = sample_article.normalized_url

        engine = DuplicateDetectionEngine(db)
        result = await engine.check(sample_raw_article)
        assert result.is_duplicate is True
        assert result.detection_layer == "url"

    async def test_title_hash_duplicate(self, db, sample_article, sample_raw_article):
        """Same normalized title should be detected as duplicate."""
        sample_raw_article.title = sample_article.title

        engine = DuplicateDetectionEngine(db)
        result = await engine.check(sample_raw_article)
        # URL is different but title is same — should detect on title layer
        assert result.is_duplicate is True
