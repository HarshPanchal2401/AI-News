"""
AI Pulse – Gemini AI Client
==============================
Async wrapper for Gemini 2.5 Flash API with rate limiting,
retry logic, and structured JSON output.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.exceptions import AIProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class GeminiClient:
    """
    Async Gemini API client with:
    - Rate limiting (15 RPM for free tier)
    - Exponential backoff retry
    - Structured JSON output mode
    - Batch processing support
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        fallback_models = [
            settings.gemini_model,
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]
        self._models = list(dict.fromkeys(model for model in fallback_models if model))
        self._json_config = types.GenerateContentConfig(
            temperature=0.1,
            top_p=0.8,
            response_mime_type="application/json",
        )
        self._text_config = types.GenerateContentConfig(
            temperature=0.3,
            top_p=0.9,
        )
        self.last_successful_model = settings.gemini_model
        self._rpm_limit = settings.gemini_max_rpm
        self._request_times: list[float] = []
        self._lock = asyncio.Lock()

    async def _wait_for_rate_limit(self) -> None:
        """Sliding window rate limiter — ensures <= RPM_LIMIT requests per minute."""
        async with self._lock:
            now = time.monotonic()
            # Remove requests older than 60 seconds
            self._request_times = [t for t in self._request_times if now - t < 60.0]

            if len(self._request_times) >= self._rpm_limit:
                # Wait until the oldest request is > 60s old
                wait_time = 60.0 - (now - self._request_times[0]) + 0.1
                logger.debug("gemini_rate_limit_wait", wait_seconds=round(wait_time, 2))
                await asyncio.sleep(wait_time)

            self._request_times.append(time.monotonic())

    async def generate_json(
        self,
        prompt: str,
        max_retries: int = 3,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """
        Generate structured JSON output from Gemini.

        Args:
            prompt: The prompt to send to Gemini.
            max_retries: Max retry attempts on failure.
            timeout_seconds: Timeout per request.

        Returns:
            Parsed JSON dict from Gemini response.

        Raises:
            AIProcessingError: If all retries fail.
        """
        last_error: Exception | None = None

        for model_name in self._models:
            for attempt in range(max_retries):
                try:
                    await self._wait_for_rate_limit()

                    loop = asyncio.get_event_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self._client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                                config=self._json_config,
                            ),
                        ),
                        timeout=timeout_seconds,
                    )

                    text = (response.text or "").strip()
                    if text.startswith("```"):
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]

                    self.last_successful_model = model_name
                    return json.loads(text)

                except json.JSONDecodeError as exc:
                    logger.warning(
                        "gemini_json_parse_error",
                        attempt=attempt + 1,
                        model=model_name,
                        error=str(exc),
                    )
                    last_error = exc
                    await asyncio.sleep(2 ** attempt)

                except asyncio.TimeoutError:
                    logger.warning("gemini_timeout", attempt=attempt + 1, model=model_name)
                    last_error = asyncio.TimeoutError("Gemini request timed out")
                    break

                except Exception as exc:
                    logger.error(
                        "gemini_api_error",
                        attempt=attempt + 1,
                        model=model_name,
                        error=str(exc),
                    )
                    last_error = exc
                    error_text = str(exc).lower()
                    if any(code in error_text for code in ["404", "not found", "invalid model"]):
                        break
                    await asyncio.sleep(2 ** attempt)

        raise AIProcessingError(
            f"Gemini failed across models {self._models}: {last_error}"
        )

    async def generate_text(
        self,
        prompt: str,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
    ) -> str:
        """
        Generate free-form text from Gemini (non-JSON mode).

        Used for market summaries, predictions, and other narrative content.

        Args:
            prompt: The prompt to send.
            max_retries: Max retry attempts.
            timeout_seconds: Timeout per request.

        Returns:
            Generated text string.
        """
        last_error: Exception | None = None

        for model_name in self._models:
            for attempt in range(max_retries):
                try:
                    await self._wait_for_rate_limit()
                    loop = asyncio.get_event_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self._client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                                config=self._text_config,
                            ),
                        ),
                        timeout=timeout_seconds,
                    )
                    self.last_successful_model = model_name
                    return (response.text or "").strip()
                except Exception as exc:
                    logger.warning(
                        "gemini_text_error",
                        attempt=attempt + 1,
                        model=model_name,
                        error=str(exc),
                    )
                    last_error = exc
                    error_text = str(exc).lower()
                    if any(code in error_text for code in ["404", "not found", "invalid model"]):
                        break
                    await asyncio.sleep(2 ** attempt)

        logger.error("gemini_text_failed", error=str(last_error))
        return ""  # Graceful fallback

    async def generate_embedding(self, text: str) -> list[float] | None:
        """
        Generate a text embedding using Gemini embedding model.

        Args:
            text: Text to embed.

        Returns:
            List of floats (embedding vector), or None on failure.
        """
        try:
            await self._wait_for_rate_limit()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._client.models.embed_content(
                    model=settings.gemini_embedding_model,
                    contents=text,
                    config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
                ),
            )
            if getattr(result, "embeddings", None):
                embedding = result.embeddings[0]
                return list(getattr(embedding, "values", []) or [])
            if isinstance(result, dict):
                embeddings = result.get("embeddings") or []
                if embeddings:
                    return embeddings[0].get("values") or embeddings[0].get("embedding")
            return None

        except Exception as exc:
            logger.warning("gemini_embedding_error", error=str(exc))
            return None


# Singleton client instance
_gemini_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
