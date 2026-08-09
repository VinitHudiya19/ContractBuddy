"""
Groq LLM wrapper for Llama-3 models.
Calls Groq API asynchronously using official python SDK.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.exceptions import LLMProviderError, LLMRateLimitError
from app.providers.llm.base import LLMMessage, LLMProvider, LLMResult


def _wrap(exc: Exception, action: str) -> LLMProviderError:
    """Turn an SDK error into ours, keeping rate limits distinguishable."""
    if getattr(exc, "status_code", None) == 429 or "rate limit" in str(exc).lower():
        return LLMRateLimitError()
    return LLMProviderError(f"Groq {action} failed: {exc}")


class GroqProvider(LLMProvider):
    name = "groq"

    # Published rates for llama-3.3-70b-versatile at time of writing.
    input_cost_per_million = 0.59
    output_cost_per_million = 0.79

    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise LLMProviderError("GROQ_API_KEY is not configured.")
        try:
            from groq import AsyncGroq
        except ImportError as exc:
            raise LLMProviderError("groq package is not installed.") from exc
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    @staticmethod
    def _to_payload(messages: list[LLMMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> LLMResult:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_payload(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise _wrap(exc, "request") from exc

        usage = resp.usage
        return LLMResult(
            text=resp.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self._model,
            provider=self.name,
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_payload(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise _wrap(exc, "stream") from exc
