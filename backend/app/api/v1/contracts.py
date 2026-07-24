"""
Contracts API routes.
Provides CRUD and AI analysis endpoints for contracts:
- Upload contract with auto AI extraction
- List contracts with metadata & risk scores
- Fetch contract detail
- Trigger deep AI analysis (/analyze)
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.contract import Contract
from app.repositories.contract_repo import ContractRepository
from app.schemas.contract import ContractCreate, ContractResponse
from app.services.contract_analysis import analyze_contract

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
) -> ContractResponse:
    """Upload a contract file, store on disk, and run instant AI metadata extraction."""
    repo = ContractRepository(db)

    # Save uploaded file
    file_suffix = Path(file.filename).suffix
    safe_name = f"{uuid4()}{file_suffix}"
    file_path = UPLOAD_DIR / safe_name
    extracted_text = ""

    try:
        content_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(content_bytes)

        # Attempt quick text extraction if PDF or TXT
        if file_suffix.lower() == ".pdf":
            try:
                import fitz
                doc = fitz.open(file_path)
                extracted_text = "\n".join([page.get_text() for page in doc])
            except Exception:
                extracted_text = title
        elif file_suffix.lower() in [".txt", ".md"]:
            extracted_text = content_bytes.decode("utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to store uploaded file") from exc

    # Run AI analysis for metadata and risk features
    ai_data = await analyze_contract(title, extracted_text)

    # Create Contract row with AI metadata
    contract = await repo.create_contract(
        title=title,
        filename=file.filename,
        organization_id=user.id,
        contract_number=ai_data.get("contract_number"),
        owner=ai_data.get("owner", user.full_name),
        department=ai_data.get("department", "Legal"),
        vendor=ai_data.get("vendor"),
        client=ai_data.get("client"),
        value=ai_data.get("value"),
        currency=ai_data.get("currency", "USD"),
        effective_date=ai_data.get("effective_date"),
        expiry_date=ai_data.get("expiry_date"),
        renewal_date=ai_data.get("renewal_date"),
        priority=ai_data.get("priority", "Medium"),
        health_score=ai_data.get("health_score", 85),
        risk_score=ai_data.get("risk_score", 15),
        missing_clauses=json.dumps(ai_data.get("missing_clauses", [])),
        obligations=json.dumps(ai_data.get("obligations", [])),
        payment_terms=ai_data.get("payment_terms"),
        parties=json.dumps(ai_data.get("parties", [])),
        auto_tags=json.dumps(ai_data.get("auto_tags", [])),
        action_items=json.dumps(ai_data.get("action_items", [])),
        compliance_flags=json.dumps(ai_data.get("compliance_flags", [])),
    )
    await repo.add_version(contract, str(file_path))
    await db.commit()
    await db.refresh(contract)

    return ContractResponse.model_validate(contract)


@router.get("/", response_model=list[ContractResponse])
async def list_contracts(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
) -> list[ContractResponse]:
    """Return all contracts for current user with full metadata and risk scores."""
    result = await db.execute(select(Contract).where(Contract.organization_id == user.id))
    contracts = result.scalars().all()
    return [ContractResponse.model_validate(c) for c in contracts]


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
) -> ContractResponse:
    """Fetch contract details by UUID."""
    result = await db.execute(
        select(Contract).where(Contract.id == contract_id, Contract.organization_id == user.id)
    )
    contract = result.scalars().first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return ContractResponse.model_validate(contract)


@router.post("/{contract_id}/analyze", response_model=ContractResponse)
async def analyze_contract_endpoint(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
) -> ContractResponse:
    """Trigger or re-run AI Contract Analysis to extract risk, obligations, missing clauses, and flags."""
    repo = ContractRepository(db)
    contract = await repo.get_by_id(contract_id)
    if not contract or contract.organization_id != user.id:
        raise HTTPException(status_code=404, detail="Contract not found")

    ai_data = await analyze_contract(contract.title, "")
    updated_contract = await repo.update_analysis(contract, ai_data)
    return ContractResponse.model_validate(updated_contract)
