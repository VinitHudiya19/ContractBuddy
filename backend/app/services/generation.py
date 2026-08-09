"""
Logic to build prompts and citations.
Funnels retrieved chunks and chat history to the LLM.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.providers.llm.base import LLMMessage
from app.services.hybrid_retrieval import RetrievedChunk

_SNIPPET_CHARS = 280

SYSTEM_PROMPT = """You are a precise document question-answering assistant.

Rules:
- Answer ONLY from the provided source excerpts. If the sources do not contain
  the answer, say so plainly — never invent information.
- Cite sources inline using their markers, e.g. [S1] or [S2][S3], immediately
  after each claim they support.
- Be concise and direct. Use the user's language and terminology.
- If sources conflict, point out the conflict and cite both."""


@dataclass
class Citation:
    marker: str
    document_id: str
    filename: str
    page: int | None
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_context(chunks: list[RetrievedChunk]) -> tuple[str, list[Citation]]:
    # Format chunks as context text for prompt, and create citation metadata objects
    citations: list[Citation] = []
    blocks: list[str] = []
    by_doc: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk)

    marker_no = 0
    for doc_chunks in by_doc.values():
        for chunk in doc_chunks:
            marker_no += 1
            marker = f"S{marker_no}"
            page_label = f", Page: {chunk.page_number}" if chunk.page_number else ""
            blocks.append(
                f"[{marker}] [Doc: {chunk.filename}{page_label}]\n{chunk.content}"
            )
            citations.append(
                Citation(
                    marker=marker,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page=chunk.page_number,
                    snippet=chunk.content[:_SNIPPET_CHARS],
                )
            )
    return "\n\n---\n\n".join(blocks), citations


def build_messages(
    question: str,
    context: str,
    history: list[tuple[str, str]] | None = None,
) -> list[LLMMessage]:
    # Combine system prompt, past conversations, context chunks and the question
    messages = [LLMMessage(role="system", content=SYSTEM_PROMPT)]
    for role, content in (history or [])[-6:]:  # last 3 exchanges
        messages.append(LLMMessage(role=role, content=content))
    messages.append(
        LLMMessage(
            role="user",
            content=(
                f"Source excerpts:\n\n{context}\n\n"
                f"Question: {question}\n\n"
                "Answer using only the sources above, citing markers like [S1]."
            ),
        )
    )
    return messages


_MARKER_RE = re.compile(r"\[S(\d+)\]")


def used_citations(answer: str, citations: list[Citation]) -> list[Citation]:
    # Extract [S1] style markers from answer text to filter out unused citations
    used_numbers = {int(m) for m in _MARKER_RE.findall(answer)}
    if not used_numbers:
        return citations
    return [c for c in citations if int(c.marker[1:]) in used_numbers]
