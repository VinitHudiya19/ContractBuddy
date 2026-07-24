"""
Repository for Contract and ContractVersion models.
Supports CRUD and metadata / AI analysis updates.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.contract import Contract, ContractVersion


class ContractRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_contract(
        self,
        title: str,
        filename: str,
        organization_id: UUID | str,
        **kwargs,
    ) -> Contract:
        """Create a Contract row with optional metadata and AI analysis attributes."""
        # Convert lists/dicts to JSON string for storage if passed as python structures
        for json_field in (
            "missing_clauses", "obligations", "parties",
            "auto_tags", "action_items", "compliance_flags"
        ):
            if json_field in kwargs and isinstance(kwargs[json_field], (list, dict)):
                kwargs[json_field] = json.dumps(kwargs[json_field])

        contract = Contract(
            id=uuid4(),
            title=title,
            filename=filename,
            status="uploaded",
            organization_id=organization_id,
            **kwargs,
        )
        self.db.add(contract)
        return contract

    async def add_version(self, contract: Contract, file_path: str) -> ContractVersion:
        """Create a new ContractVersion linked to the given contract."""
        version = ContractVersion(
            id=uuid4(),
            contract_id=contract.id,
            version_number="1.0",
            file_path=file_path,
        )
        self.db.add(version)
        return version

    async def get_by_id(self, contract_id: UUID | str) -> Contract | None:
        result = await self.db.execute(select(Contract).where(Contract.id == contract_id))
        return result.scalars().first()

    async def update_analysis(self, contract: Contract, analysis: dict) -> Contract:
        """Update contract with AI analysis fields."""
        for field in [
            "contract_number", "owner", "department", "vendor", "client",
            "value", "currency", "effective_date", "expiry_date", "renewal_date",
            "priority", "health_score", "risk_score", "payment_terms"
        ]:
            if field in analysis and analysis[field] is not None:
                setattr(contract, field, analysis[field])

        for json_field in [
            "missing_clauses", "obligations", "parties",
            "auto_tags", "action_items", "compliance_flags"
        ]:
            if json_field in analysis and analysis[json_field] is not None:
                val = analysis[json_field]
                setattr(contract, json_field, json.dumps(val) if isinstance(val, (list, dict)) else str(val))

        contract.status = "ai_processed"
        await self.db.commit()
        await self.db.refresh(contract)
        return contract
