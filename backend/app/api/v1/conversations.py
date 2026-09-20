"""
Conversation and message chat endpoints.
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.v1.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.exceptions import AppError, ConversationNotFoundError
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal, get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import ai_rate_limit
from app.models.conversation import Conversation
from app.models.enums import MessageRole
from app.models.user import User
from app.providers.factory import get_llm
from app.repositories.conversation_repo import ConversationRepository
from app.schemas.conversation import (
    AskRequest,
    AskResponse,
    ConversationCreate,
    ConversationPublic,
    ConversationUpdate,
    MessagePublic,
)
from app.services.generation import build_context, build_messages, used_citations
from app.services.hybrid_retrieval import retrieve

logger = get_logger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_NO_CONTEXT_ANSWER = (
    "I couldn't find anything relevant in your documents for that question. "
    "Please make sure your files are uploaded and indexed."
)


@router.post("", response_model=ConversationPublic, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationPublic:
    repo = ConversationRepository(db)
    conversation = await repo.create(
        user_id=user.id,
        title=body.title,
        document_scope=body.document_scope,
    )
    await db.commit()
    return ConversationPublic.model_validate(conversation)


@router.get("", response_model=list[ConversationPublic])
async def list_conversations(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationPublic]:
    repo = ConversationRepository(db)
    return await repo.list_for_user(user.id, limit=limit, offset=offset)


@router.patch("/{conversation_id}", response_model=ConversationPublic)
async def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationPublic:
    """Rename a conversation or change which documents it searches."""
    repo = ConversationRepository(db)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise ConversationNotFoundError()

    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"]:
        conversation.title = fields["title"]
    if "document_scope" in fields:
        # An empty list means "no filter", stored as NULL.
        conversation.document_scope = fields["document_scope"] or None

    await db.commit()
    await db.refresh(conversation)
    return ConversationPublic.model_validate(conversation)


@router.get("/{conversation_id}/messages", response_model=list[MessagePublic])
async def get_messages(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessagePublic]:
    repo = ConversationRepository(db)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise ConversationNotFoundError()
    messages = await repo.get_messages(conversation_id)
    return [MessagePublic.model_validate(m) for m in messages]


@router.delete("/{conversation_id}", response_model=None, status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = ConversationRepository(db)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise ConversationNotFoundError()
    await repo.delete(conversation)
    await db.commit()


@router.post("/{conversation_id}/messages", response_model=AskResponse,
             dependencies=[Depends(ai_rate_limit)])
async def ask(
    conversation_id: UUID,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response | AskResponse:
    repo = ConversationRepository(db)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise ConversationNotFoundError()

    # Save user message
    await repo.add_message(
        conversation=conversation, role=MessageRole.user, content=body.question
    )
    await db.commit()

    # Retrieve context chunks
    scope = list(conversation.document_scope) if conversation.document_scope else None
    chunks, _ = await retrieve(
        db, user_id=user.id, query=body.question, document_scope=scope
    )
    history = await repo.recent_history(conversation_id, limit=6)

    if body.stream:
        return EventSourceResponse(
            _stream_answer(
                conversation_id=conversation.id,
                user_question=body.question,
                chunks=chunks,
                history=history[:-1],
            ),
            media_type="text/event-stream",
        )
    return await _full_answer(
        db, repo, conversation, body.question, chunks, history[:-1]
    )


async def _generate_setup(question: str, chunks, history):
    context, citations = build_context(chunks)
    messages = build_messages(question, context, history)
    return messages, citations


async def _full_answer(db, repo, conversation, question, chunks, history):
    llm = get_llm()

    if not chunks:
        answer = _NO_CONTEXT_ANSWER
        final_citations = []
    else:
        messages, citations = await _generate_setup(question, chunks, history)
        result = await llm.generate(messages)
        answer = result.text
        final_citations = [c.to_dict() for c in used_citations(answer, citations)]

    message = await repo.add_message(
        conversation=conversation,
        role=MessageRole.assistant,
        content=answer,
        citations=final_citations,
    )
    await db.commit()
    return AskResponse(
        message=MessagePublic.model_validate(message)
    )


async def _stream_answer(*, conversation_id, user_question, chunks, history):
    llm = get_llm()

    if not chunks:
        yield {"event": "meta", "data": json.dumps({"citations": []})}
        yield {"event": "token", "data": json.dumps({"t": _NO_CONTEXT_ANSWER})}
        answer, final_citations = _NO_CONTEXT_ANSWER, []
    else:
        messages, citations = await _generate_setup(user_question, chunks, history)
        yield {
            "event": "meta",
            "data": json.dumps(
                {"citations": [c.to_dict() for c in citations]}
            ),
        }
        parts = []
        try:
            async for token in llm.stream(messages):
                parts.append(token)
                yield {"event": "token", "data": json.dumps({"t": token})}
        except Exception as exc:
            logger.error("stream generation failed", exc_info=exc)
            # AppError messages are written for users and carry no internals, so
            # they are safe to forward; anything else gets the generic text.
            known = isinstance(exc, AppError)
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "code": exc.code if known else "LLM_PROVIDER_ERROR",
                        "message": exc.message if known else "Generation failed. Please retry.",
                    }
                ),
            }
            return
        answer = "".join(parts)
        final_citations = [c.to_dict() for c in used_citations(answer, citations)]

    async with AsyncSessionLocal() as session:
        repo = ConversationRepository(session)
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None:
            message = await repo.add_message(
                conversation=conversation,
                role=MessageRole.assistant,
                content=answer,
                citations=final_citations,
            )
            await session.commit()
            message_id = str(message.id)
        else:
            message_id = None

    yield {
        "event": "done",
        "data": json.dumps(
            {
                "message_id": message_id,
                "citations": final_citations,
            }
        ),
    }
