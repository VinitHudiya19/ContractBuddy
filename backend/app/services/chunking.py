"""
Text chunking helper.
Chunks are around 500 tokens with 50-token overlap.
Maps each chunk to the page it started on so we can cite it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings

# 1 token ~= 0.75 English words
_WORDS_PER_TOKEN = 0.75


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int
    page_number: int | None


def _approx_tokens(words: int) -> int:
    # Quick word count to token estimate
    return max(1, round(words / _WORDS_PER_TOKEN))


def _clean(text: str) -> str:
    # Clean up weird spacing and bad characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(
    pages: list[tuple[int | None, str]],
    *,
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    chunk_tokens = chunk_tokens or settings.chunk_tokens
    overlap_tokens = overlap_tokens or settings.chunk_overlap_tokens
    words_per_chunk = max(20, int(chunk_tokens * _WORDS_PER_TOKEN))
    overlap_words = min(int(overlap_tokens * _WORDS_PER_TOKEN), words_per_chunk // 2)

    # Convert all pages into a single list of words, tracking pages
    words: list[str] = []
    word_pages: list[int | None] = []
    for page_number, raw in pages:
        text = _clean(raw)
        if not text:
            continue
        for w in text.split():
            words.append(w)
            word_pages.append(page_number)

    if not words:
        return []

    chunks: list[Chunk] = []
    step = words_per_chunk - overlap_words
    index = 0
    for start in range(0, len(words), step):
        window = words[start : start + words_per_chunk]
        if not window:
            break
        # Don't create a chunk if it's just repeating overlapping words
        if start > 0 and len(window) <= overlap_words:
            break
        content = " ".join(window)
        chunks.append(
            Chunk(
                index=index,
                content=content,
                token_count=_approx_tokens(len(window)),
                page_number=word_pages[start],
            )
        )
        index += 1
        if start + words_per_chunk >= len(words):
            break

    return chunks
