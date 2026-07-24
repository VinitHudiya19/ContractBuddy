from __future__ import annotations

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


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


class ContractAIAnalysis(BaseModel):
    """AI analysis result breakdown for a contract."""
    health_score: int = Field(85, ge=0, le=100)
    risk_score: int = Field(15, ge=0, le=100)
    missing_clauses: list[str] = []
    obligations: list[str] = []
    payment_terms: str = "Standard Payment Terms"
    parties: list[str] = []
    auto_tags: list[str] = []
    action_items: list[str] = []
    compliance_flags: list[str] = []


class ContractResponse(BaseModel):
    """Contract response model with full metadata and AI analysis output."""
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
    currency: str | None = "USD"
    effective_date: str | None = None
    expiry_date: str | None = None
    renewal_date: str | None = None
    priority: str | None = "Medium"

    # AI Analysis Fields
    health_score: int | None = 85
    risk_score: int | None = 15
    missing_clauses: str | None = "[]"
    obligations: str | None = "[]"
    payment_terms: str | None = None
    parties: str | None = "[]"
    auto_tags: str | None = "[]"
    action_items: str | None = "[]"
    compliance_flags: str | None = "[]"
