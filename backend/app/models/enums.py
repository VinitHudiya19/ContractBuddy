"""
Shared enum definitions.
"""
from __future__ import annotations

import enum


class DocumentStatus(str, enum.Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class FileType(str, enum.Enum):
    pdf = "pdf"
    docx = "docx"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ContractStatus(str, enum.Enum):
    draft = "draft"
    uploaded = "uploaded"
    ai_processed = "ai_processed"
    review = "review"
    legal_approval = "legal_approval"
    finance_approval = "finance_approval"
    final_approval = "final_approval"
    active = "active"
    expired = "expired"
    archived = "archived"

