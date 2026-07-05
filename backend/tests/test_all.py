"""
Tests for Verification Engine, Ranking, Personalization, and API endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.news_fetchers.base import RawArticle
from app.services.verification.engine import (
    CrossReferencer,
    TrustResult,
    VerificationEngine,
    compute_trust_score,
)
from app.services.ranking.ranker import compute_final_score
from app.utils.date_utils import freshness_score, hours_ago


# ── Verification Tests ────────────────────────────────────────────────────────

class TestTrustScoring:
    def _make_article(self, domain: str, is_official: bool = False, hours_old: float = 2.0) -> RawArticle:
        return RawArticle(
            title="Test Article",
            url=f"https://{domain}/article",
            source_name="test",
            source_domain=domain,
            published_at=hours_ago(hours_old),
            is_official=is_official,
        )

    def test_official_company_source_gets_high_score(self):
        article = self._make_article("openai.com", is_official=True)
        result = compute_trust_score(article)
        assert result.trust_score >= 90.0
        assert result.is_verified is True

    def test_tier1_media_gets_high_score(self):
        article = self._make_article("reuters.com")
        result = compute_trust_score(article)
        assert result.trust_score >= 75.0
        assert result.is_verified is True

    def test_unknown_source_gets_low_score(self):
        article = self._make_article("some-random-blog.xyz", hours_old=24.0)
        result = compute_trust_score(article)
        assert result.trust_score < 40.0
        assert result.is_verified is False

    def test_corroboration_increases_score(self):
        article = self._make_article("techcrunch.com")
        single = compute_trust_score(article, corroboration_count=1)
        triple = compute_trust_score(article, corroboration_count=3)
        assert triple.trust_score > single.trust_score

    def test_fresh_article_gets_bonus(self):
        fresh = self._make_article("techcrunch.com", hours_old=1.0)
        old = self._make_article("techcrunch.com", hours_old=72.0)
        assert compute_trust_score(fresh).trust_score > compute_trust_score(old).trust_score

    def test_very_old_article_penalized(self):
        old = self._make_article("reuters.com", hours_old=72.0)
        result = compute_trust_score(old)
        # Penalty applied
        assert "old" in result.notes

    def test_trust_score_capped_at_100(self):
        article = self._make_article("openai.com", is_official=True)
        result = compute_trust_score(article, corroboration_count=10)
        assert result.trust_score <= 100.0


class TestCrossReferencer:
    def _make_articles(self, titles_and_domains: list[tuple[str, str]]) -> list[RawArticle]:
        return [
            RawArticle(
                title=title,
                url=f"https://{domain}/article",
                source_name=domain.split(".")[0],
                source_domain=domain,
            )
            for title, domain in titles_and_domains
        ]

    def test_groups_related_articles(self):
        articles = self._make_articles([
            ("OpenAI launches GPT-6", "openai.com"),
            ("OpenAI unveils GPT-6 model", "reuters.com"),
            ("Google releases Gemini 3", "deepmind.google"),
        ])
        xref = CrossReferencer()
        groups = xref.group_by_story(articles)
        # GPT-6 articles should be grouped
        assert any(len(v) >= 2 for v in groups.values())

    def test_counts_trusted_sources(self):
        articles = self._make_articles([
            ("OpenAI launches GPT-6", "openai.com"),
            ("OpenAI unveils GPT-6 model", "reuters.com"),
        ])
        xref = CrossReferencer()
        count = xref.count_trusted_sources(articles)
        assert count == 2  # Both are trusted domains


# ── Ranking Tests ─────────────────────────────────────────────────────────────

class TestRanking:
    def test_high_importance_high_trust_scores_high(self):
        score = compute_final_score(
            importance_score=90.0,
            trust_score=90.0,
            published_at=datetime.now(timezone.utc),
            is_official=True,
        )
        assert score > 70.0

    def test_low_importance_low_trust_scores_low(self):
        score = compute_final_score(
            importance_score=20.0,
            trust_score=20.0,
            published_at=hours_ago(60),
            is_official=False,
        )
        assert score < 30.0

    def test_official_source_scores_higher_than_unofficial(self):
        official = compute_final_score(90.0, 90.0, datetime.now(timezone.utc), True)
        unofficial = compute_final_score(90.0, 90.0, datetime.now(timezone.utc), False)
        assert official > unofficial

    def test_fresh_article_scores_higher_than_stale(self):
        fresh = compute_final_score(80.0, 80.0, datetime.now(timezone.utc), False)
        stale = compute_final_score(80.0, 80.0, hours_ago(48), False)
        assert fresh > stale

    def test_score_is_0_to_100(self):
        for imp in [0, 50, 100]:
            for trust in [0, 50, 100]:
                score = compute_final_score(imp, trust, datetime.now(timezone.utc), False)
                assert 0 <= score <= 100


# ── Personalization Tests ─────────────────────────────────────────────────────

class TestPersonalization:
    @pytest.mark.asyncio
    async def test_generates_brief_for_user(self, db, sample_user, sample_article, mock_redis):
        from app.services.personalization.engine import PersonalizationEngine
        engine = PersonalizationEngine(db)
        brief = await engine.generate_brief_for_user(sample_user.id, articles=[sample_article])
        assert brief is not None
        assert len(brief.article_ids) >= 1

    @pytest.mark.asyncio
    async def test_blocked_topic_removes_article(self, db, sample_user, sample_article):
        """Articles with blocked topics should not appear in the brief."""
        from app.models.user import UserPreferences
        from sqlalchemy import select

        result = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == sample_user.id)
        )
        prefs = result.scalar_one_or_none()
        if prefs:
            prefs.blocked_topics = ["LLMs"]
            await db.commit()

        from app.services.personalization.engine import PersonalizationEngine
        engine = PersonalizationEngine(db)
        brief = await engine.generate_brief_for_user(sample_user.id, articles=[sample_article])
        # Article should be excluded (LLMs is blocked)
        if brief:
            assert str(sample_article.id) not in [str(aid) for aid in brief.article_ids]


# ── API Tests ─────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client, mock_redis):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestNewsEndpoints:
    @pytest.mark.asyncio
    async def test_get_news_returns_list(self, client, sample_article, mock_redis):
        response = await client.get("/api/v1/news")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_get_article_by_id(self, client, sample_article, mock_redis):
        response = await client.get(f"/api/v1/news/{sample_article.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(sample_article.id)
        assert data["title"] == sample_article.title

    @pytest.mark.asyncio
    async def test_get_nonexistent_article_returns_404(self, client, mock_redis):
        import uuid
        fake_id = uuid.uuid4()
        response = await client.get(f"/api/v1/news/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_search_returns_results(self, client, sample_article, mock_redis):
        response = await client.get("/api/v1/news/search?q=OpenAI")
        assert response.status_code == 200


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_register_new_user(self, client, mock_redis):
        response = await client.post("/api/v1/auth/register", json={
            "email": "newuser@test.com",
            "password": "securepass123",
            "display_name": "New User",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@test.com"

    @pytest.mark.asyncio
    async def test_register_duplicate_email_returns_409(self, client, sample_user, mock_redis):
        response = await client.post("/api/v1/auth/register", json={
            "email": sample_user.email,
            "password": "securepass123",
        })
        assert response.status_code == 409
