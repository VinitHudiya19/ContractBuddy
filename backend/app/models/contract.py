from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ContractStatus
from app.models.types import GUID, new_uuid


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status"), nullable=False, default=ContractStatus.draft
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    organization_id: Mapped[GUID] = mapped_column(GUID(), nullable=False)

    # --- Extended Contract Metadata ---
    contract_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    client: Mapped[str | None] = mapped_column(String(150), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), default="USD", nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    renewal_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), default="Medium", nullable=True)

    # --- AI Analysis & Extractions ---
    # "llm" when a model produced the analysis, "rules" when the deterministic
    # text heuristics did. Surfaced in the UI so the two are never confused.
    analysis_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    health_score: Mapped[int | None] = mapped_column(Integer, default=80, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, default=20, nullable=True)
    missing_clauses: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON list
    obligations: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON list
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON string
    parties: Mapped[str | None] = mapped_column(Text, nullable=True)              # JSON list
    auto_tags: Mapped[str | None] = mapped_column(Text, nullable=True)             # JSON list
    action_items: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON list
    compliance_flags: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON list

    versions: Mapped[list[ContractVersion]] = relationship(
        "ContractVersion", back_populates="contract", cascade="all, delete-orphan"
    )


class ContractVersion(Base):
    __tablename__ = "contract_versions"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    contract_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[str] = mapped_column(String, nullable=False, default="1.0")
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    contract: Mapped[Contract] = relationship("Contract", back_populates="versions")
