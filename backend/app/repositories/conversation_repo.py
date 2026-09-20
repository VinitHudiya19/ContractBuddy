"""
Database repository for conversations and messages.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.enums import MessageRole


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return await self.session.get(Conversation, conversation_id)

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int = 0
    ) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            # id breaks ties so a row can't shift between pages and get served
            # twice (or skipped) when timestamps collide.
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: UUID,
        title: str | None = None,
        document_scope: list[UUID] | None = None,
    ) -> Conversation:
        conversation = Conversation(
            user_id=user_id,
            title=title or "New conversation",
            document_scope=document_scope,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()

    async def get_messages(self, conversation_id: UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def add_message(
        self,
        *,
        conversation: Conversation,
        role: MessageRole,
        content: str,
        citations: list[dict] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            citations=citations,
        )
        self.session.add(message)
        if role is MessageRole.user and conversation.title == "New conversation":
            conversation.title = content[:80] + ("..." if len(content) > 80 else "")
        conversation.updated_at = func.now()
        await self.session.flush()
        return message

    async def recent_history(
        self, conversation_id: UUID, limit: int = 6
    ) -> list[tuple[str, str]]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        return [(msg.role.value, msg.content) for msg in reversed(messages)]
