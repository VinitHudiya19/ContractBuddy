"""
Repository for Contract and ContractVersion.

List-valued analysis fields are serialised to JSON text here so the same schema
runs on SQLite and Postgres; the response schema decodes them back into arrays.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractVersion
from app.models.enums import ContractStatus

# Columns that live as JSON text.
_JSON_FIELDS = (
    "missing_clauses",
    "obligations",
    "parties",
    "auto_tags",
    "action_items",
    "compliance_flags",
)
# Plain columns an analysis run is allowed to write.
_SCALAR_FIELDS = (
    "analysis_source",
    "contract_number",
    "owner",
    "department",
    "vendor",
    "client",
    "value",
    "currency",
    "effective_date",
    "expiry_date",
    "renewal_date",
    "priority",
    "health_score",
    "risk_score",
    "payment_terms",
)


def _encode(value) -> str:
    return json.dumps(value if isinstance(value, (list, dict)) else [str(value)])


class ContractRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_contract(
        self,
        title: str,
        filename: str,
        organization_id: UUID | str,
        **analysis,
    ) -> Contract:
        """Create a contract row from an analysis result."""
        fields = {k: v for k, v in analysis.items() if k in _SCALAR_FIELDS}
        fields.update(
            {k: _encode(analysis[k]) for k in _JSON_FIELDS if analysis.get(k) is not None}
        )

        contract = Contract(
            id=uuid4(),
            title=title,
            filename=filename,
            status=ContractStatus.ai_processed,
            organization_id=organization_id,
            **fields,
        )
        self.db.add(contract)
        return contract

    async def add_version(self, contract: Contract, file_path: str) -> ContractVersion:
        """Attach a stored file to the contract as a new version."""
        existing = (
            (
                await self.db.execute(
                    select(ContractVersion).where(
                        ContractVersion.contract_id == contract.id
                    )
                )
            )
            .scalars()
            .all()
        )

        version = ContractVersion(
            id=uuid4(),
            contract_id=contract.id,
            version_number=f"{len(existing) + 1}.0",
            file_path=file_path,
        )
        self.db.add(version)
        return version

    async def get_by_id(self, contract_id: UUID | str) -> Contract | None:
        result = await self.db.execute(select(Contract).where(Contract.id == contract_id))
        return result.scalars().first()

    async def update_analysis(self, contract: Contract, analysis: dict) -> Contract:
        """Overwrite the analysis columns with a fresh result."""
        for field in _SCALAR_FIELDS:
            if field in analysis:
                setattr(contract, field, analysis[field])

        for field in _JSON_FIELDS:
            if field in analysis and analysis[field] is not None:
                setattr(contract, field, _encode(analysis[field]))

        contract.status = ContractStatus.ai_processed
        await self.db.commit()
        await self.db.refresh(contract)
        return contract
