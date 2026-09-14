"""
Document summarization using map-reduce over the chunks.

Map: chunks are grouped into context-window-sized batches; each batch is
summarized independently. Reduce: the partial summaries are summarized into one
final answer. Single-batch documents skip the reduce step. Reuses the same
pluggable LLMProvider (and therefore the retry/breaker/fallback stack).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentNotFoundError, DocumentNotReadyError
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.providers.factory import get_llm
from app.providers.llm.base import LLMMessage

logger = get_logger(__name__)

# ~words per map batch; conservative so any provider's context fits.
_BATCH_WORDS = 2200

_MAP_PROMPT = (
    "Summarize the following document excerpt in 4-6 tight bullet points. "
    "Preserve key facts, figures, names and conclusions.\n\n{body}"
)
_REDUCE_PROMPT = (
    "You are given partial summaries of one document (or a set of documents). "
    "Merge them into one clear summary: a 2-3 sentence overview followed by "
    "5-8 bullet points of the most important facts.\n\n{body}"
)


async def summarize_documents(
    session: AsyncSession, *, user_id: UUID, document_ids: list[UUID]
) -> tuple[str, dict]:
    """
    Map-reduce summarize one or more documents.
    Returns (summary_text, usage_stats).
    """
    # Ownership + readiness checks.
    result = await session.execute(
        select(Document).where(Document.id.in_(document_ids), Document.user_id == user_id)
    )
    documents = list(result.scalars().all())
    if len(documents) != len(set(document_ids)):
        raise DocumentNotFoundError()
    not_ready = [d for d in documents if d.status is not DocumentStatus.ready]
    if not_ready:
        raise DocumentNotReadyError(
            f"Document(s) still processing: {', '.join(d.filename for d in not_ready)}"
        )

    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id.in_(document_ids))
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        raise DocumentNotReadyError("No content available to summarize.")

    llm = get_llm()
    total_prompt = total_completion = 0

    # ---- Map ----
    batches: list[str] = []
    current: list[str] = []
    words = 0
    for chunk in chunks:
        chunk_words = len(chunk.content.split())
        if words + chunk_words > _BATCH_WORDS and current:
            batches.append("\n\n".join(current))
            current, words = [], 0
        current.append(chunk.content)
        words += chunk_words
    if current:
        batches.append("\n\n".join(current))

    partials: list[str] = []
    for batch in batches:
        result = await llm.generate(
            [LLMMessage(role="user", content=_MAP_PROMPT.format(body=batch))],
            temperature=0.2,
            max_tokens=512,
        )
        partials.append(result.text.strip())
        total_prompt += result.prompt_tokens
        total_completion += result.completion_tokens

    # ---- Reduce (skip when a single batch already is the summary) ----
    if len(partials) == 1:
        summary = partials[0]
    else:
        result = await llm.generate(
            [LLMMessage(role="user", content=_REDUCE_PROMPT.format(body="\n\n".join(partials)))],
            temperature=0.2,
            max_tokens=768,
        )
        summary = result.text.strip()
        total_prompt += result.prompt_tokens
        total_completion += result.completion_tokens

    stats = {
        "batches": len(batches),
        "chunks": len(chunks),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "provider": llm.name,
        "estimated_cost_usd": llm.estimate_cost(total_prompt, total_completion),
    }
    logger.info("summarization complete", extra=stats)
    return summary, stats
