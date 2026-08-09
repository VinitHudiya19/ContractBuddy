"""
Base interface for LLM calls.
We keep a simple base class so our chat logic works cleanly with Groq / Llama 3.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class LLMMessage:
    # represents a single turn in the chat history
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResult:
    # response structure returned after text generation
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    provider: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    # abstract base class for text generation models
    name: str = "base"

    # USD per 1M tokens. Override per provider; 0 means "free / local".
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Rough spend for one call, used for the usage stats in summaries."""
        cost = (
            prompt_tokens * self.input_cost_per_million
            + completion_tokens * self.output_cost_per_million
        ) / 1_000_000
        return round(cost, 6)

    @abstractmethod
    async def generate(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> LLMResult:
        # returns full response string
        pass

    @abstractmethod
    async def stream(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        # yields text chunks as they are generated
        raise NotImplementedError
        yield ""
