"""
Extractive fallback used when no LLM API key is configured.

It does **not** pretend to be a language model. It selects the sentences from
the retrieved context that overlap most with the question and returns them
verbatim with their citation markers, prefixed by a notice explaining that
generation is disabled. That keeps the retrieval half of the pipeline
demonstrable offline while never presenting invented text as a model answer.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.providers.llm.base import LLMMessage, LLMProvider, LLMResult

_NOTICE = (
    "_No LLM API key is configured, so this is an extractive answer: the "
    "passages below are quoted directly from your documents rather than "
    "written by a model. Set `GROQ_API_KEY` in `.env` for generated answers._"
)
_NO_MATCH = (
    "I could not find a passage in your documents that matches that question."
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_MARKER_RE = re.compile(r"\[S(\d+)\]")
_MAX_SENTENCES = 4


class ExtractiveProvider(LLMProvider):
    name = "extractive"

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> LLMResult:
        question, context = _split(messages)
        text = _extract(question, context)
        return LLMResult(
            text=text,
            prompt_tokens=len(question.split()),
            completion_tokens=len(text.split()),
            model="extractive-v1",
            provider=self.name,
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float = 0.2, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        question, context = _split(messages)
        text = _extract(question, context)
        # Emit in word-sized pieces so the SSE path is exercised identically.
        for i, word in enumerate(text.split(" ")):
            yield word if i == 0 else " " + word
            await asyncio.sleep(0.01)


def _split(messages: list[LLMMessage]) -> tuple[str, str]:
    """Pull the question and the source block out of the assembled prompt."""
    user_content = next(
        (m.content for m in reversed(messages) if m.role == "user"), ""
    )
    question = user_content
    context = ""
    if "Source excerpts:" in user_content:
        _, _, rest = user_content.partition("Source excerpts:")
        context, _, tail = rest.partition("Question:")
        question = tail.split("\n")[0].strip() or user_content
    return question.strip(), context.strip()


def _extract(question: str, context: str) -> str:
    if not context:
        return f"{_NOTICE}\n\n{_NO_MATCH}"

    keywords = set(_WORD_RE.findall(question.lower()))
    scored: list[tuple[int, str]] = []

    def overlap_score(sentence: str) -> int:
        """
        Count matching keywords, treating a shared prefix as a match so
        "payment" still finds "pay" without pulling in a stemming dependency.
        """
        words = set(_WORD_RE.findall(sentence.lower()))
        hits = 0
        for keyword in keywords:
            if any(
                word == keyword
                or (word.startswith(keyword[:4]) and len(keyword) >= 4)
                or (keyword.startswith(word[:4]) and len(word) >= 4)
                for word in words
            ):
                hits += 1
        return hits

    # Blocks look like: "[S1] [Doc: name, Page: 2]\n<chunk text>"
    for block in context.split("\n\n---\n\n"):
        marker_match = _MARKER_RE.search(block)
        marker = marker_match.group(0) if marker_match else ""
        body = block.split("\n", 1)[1] if "\n" in block else block
        for sentence in _SENTENCE_RE.split(body):
            sentence = sentence.strip()
            if len(sentence) < 30:
                continue
            overlap = overlap_score(sentence)
            if overlap:
                scored.append((overlap, f"{sentence} {marker}".strip()))

    if not scored:
        return f"{_NOTICE}\n\n{_NO_MATCH}"

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = [sentence for _, sentence in scored[:_MAX_SENTENCES]]
    return f"{_NOTICE}\n\n" + "\n\n".join(f"> {s}" for s in best)
