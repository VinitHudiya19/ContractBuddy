"""
Contract request/response schemas.

The list-valued analysis fields are stored as JSON text (so the same schema
works on SQLite and Postgres) but are exposed to the API as real arrays — the
frontend should never have to `JSON.parse` a field out of a JSON response.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractCreate(BaseModel):
    """Payload for creating/uploading a contract with optional metadata."""

    title: str = Field(..., description="Human readable contract title")
    contract_number: str | None = Field(None, description="Unique contract identifier")
    owner: str | None = None
    department: str | None = None
    vendor: str | None = None
    client: str | None = None
    value: float | None = None
    currency: str | None = "USD"
    effective_date: str | None = None
    expiry_date: str | None = None
    renewal_date: str | None = None
    priority: str | None = "Medium"


class ContractUpdate(BaseModel):
    """Payload for updating contract metadata."""

    title: str | None = None
    status: str | None = None
    owner: str | None = None
    department: str | None = None
    vendor: str | None = None
    client: str | None = None
    value: float | None = None
    currency: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    renewal_date: str | None = None
    priority: str | None = None


class ContractResponse(BaseModel):
    """Contract with its full metadata and analysis output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    filename: str
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    # Metadata
    contract_number: str | None = None
    owner: str | None = None
    department: str | None = None
    vendor: str | None = None
    client: str | None = None
    value: float | None = None
    currency: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    renewal_date: str | None = None
    priority: str | None = None

    # Analysis
    analysis_source: str | None = None
    health_score: int | None = None
    risk_score: int | None = None
    payment_terms: str | None = None
    missing_clauses: list[str] = []
    obligations: list[str] = []
    parties: list[str] = []
    auto_tags: list[str] = []
    action_items: list[str] = []
    compliance_flags: list[str] = []

    @field_validator(
        "missing_clauses",
        "obligations",
        "parties",
        "auto_tags",
        "action_items",
        "compliance_flags",
        mode="before",
    )
    @classmethod
    def _decode_json_list(cls, value: Any) -> list[str]:
        """Accept a real list, a JSON-encoded list, or None from the column."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return [value] if value.strip() else []
            if isinstance(decoded, list):
                return [str(v) for v in decoded]
            return [str(decoded)] if decoded else []
        return []
