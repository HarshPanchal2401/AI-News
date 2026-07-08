import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.dependencies import get_current_user
from app.models.user import User, UserPreferences
from app.models.news_article import NewsArticle

@pytest.mark.asyncio
async def test_get_suggestions_personalized(client, sample_user, sample_article, mock_redis, mock_gemini_client):
    # Override get_current_user in the app
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: sample_user

    # Mock the Gemini return value for personalized suggestions
    mock_gemini_client.generate_json = AsyncMock(return_value={
        "summary": "Focus on adopting local quantization techniques and MCP servers.",
        "suggestions": [
            {
                "title": "Adopt local model quantization",
                "description": f"Hey {sample_user.display_name}, since you're tracking local model inference, check out the new quantization repository today.",
                "action_item": "Spend 10 minutes reading their deployment markdown script to see how to implement it locally.",
                "impact": "High",
                "relevance": "Matches your preference for LLMs and local inference."
            }
        ]
    })

    response = await client.get("/api/v1/intelligence/suggestions?suggestion_type=personalized")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "suggestions" in data
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["title"] == "Adopt local model quantization"

    # Clean up overrides
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_get_suggestions_market(client, sample_user, sample_article, mock_redis, mock_gemini_client):
    # Override get_current_user in the app
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: sample_user

    # Mock the Gemini return value for market suggestions
    mock_gemini_client.generate_json = AsyncMock(return_value={
        "summary": "Commercialize local inference APIs and expand model integrations.",
        "suggestions": [
            {
                "title": "Scale enterprise MCP connector templates",
                "description": "Enterprises lack ready-to-run MCP servers for secure database access.",
                "action_item": "Spin up a boilerplate PostgreSQL connector template.",
                "impact": "High",
                "relevance": "Matches recent rise in enterprise MCP news."
            }
        ]
    })

    response = await client.get("/api/v1/intelligence/suggestions?suggestion_type=market")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "suggestions" in data
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["title"] == "Scale enterprise MCP connector templates"

    # Clean up overrides
    app.dependency_overrides.clear()
