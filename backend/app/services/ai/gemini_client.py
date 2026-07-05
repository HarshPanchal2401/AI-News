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

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

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
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config=GenerationConfig(
                temperature=0.1,          # Low temp for consistent structured output
                top_p=0.8,
                response_mime_type="application/json",
            ),
        )
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

        for attempt in range(max_retries):
            try:
                await self._wait_for_rate_limit()

                # Run in thread pool (Gemini SDK is sync)
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._model.generate_content(prompt),
                    ),
                    timeout=timeout_seconds,
                )

                text = response.text.strip()
                # Strip markdown code fences if present
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]

                return json.loads(text)

            except json.JSONDecodeError as exc:
                logger.warning(
                    "gemini_json_parse_error",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                last_error = exc
                await asyncio.sleep(2 ** attempt)

            except asyncio.TimeoutError:
                logger.warning("gemini_timeout", attempt=attempt + 1)
                last_error = asyncio.TimeoutError("Gemini request timed out")
                await asyncio.sleep(2 ** attempt)

            except Exception as exc:
                logger.error(
                    "gemini_api_error",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                last_error = exc
                await asyncio.sleep(2 ** attempt)

        raise AIProcessingError(
            f"Gemini failed after {max_retries} attempts: {last_error}"
        )

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
                lambda: genai.embed_content(
                    model=settings.gemini_embedding_model,
                    content=text,
                    task_type="SEMANTIC_SIMILARITY",
                ),
            )
            return result["embedding"]

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
