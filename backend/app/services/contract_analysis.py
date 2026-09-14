"""
Pulls structured fields out of a contract.

Asks the LLM for a JSON object, then checks and converts every field before it
goes near the database. Models do return a string where a number should be, or
wrap the JSON in a code fence, or skip a key, so none of it can be trusted
as-is.

With no LLM (or if the JSON is unusable) it falls back to regex and keyword
rules over the text. Either way the result carries `analysis_source`, so the UI
can show which one produced it.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.providers.factory import get_llm
from app.providers.llm.base import LLMMessage

logger = get_logger(__name__)

_MAX_CHARS = 12_000

# Clauses a commercial agreement is normally expected to contain. Absence is
# what drives both the "missing clauses" list and the risk score.
_EXPECTED_CLAUSES: dict[str, tuple[str, ...]] = {
    "Termination": ("terminat",),
    "Limitation of Liability": ("liabilit", "indemnif"),
    "Confidentiality": ("confidential", "non-disclosure", "nondisclosure"),
    "Governing Law": ("governing law", "jurisdiction", "governed by"),
    "Payment Terms": ("payment", "invoice", "fees"),
    "Dispute Resolution": ("dispute", "arbitrat", "mediation"),
    "Data Protection": ("gdpr", "data protection", "personal data", "privacy"),
    "Intellectual Property": ("intellectual property", "ownership", "copyright"),
    "Service Levels": ("service level", "sla", "uptime", "availability"),
    "Force Majeure": ("force majeure",),
}

_PROMPT = """You are a contract analyst. Analyse the contract below and return a single JSON object.

Rules:
- Return raw JSON only. No markdown, no code fences, no commentary.
- Use null for anything the contract does not state. Never invent values.
- health_score and risk_score are integers 0-100 and should sum to roughly 100.
- Dates use YYYY-MM-DD.

Schema:
{{
  "contract_number": string|null,
  "owner": string|null,
  "department": string|null,
  "vendor": string|null,
  "client": string|null,
  "value": number|null,
  "currency": string|null,
  "effective_date": string|null,
  "expiry_date": string|null,
  "renewal_date": string|null,
  "priority": "High"|"Medium"|"Low",
  "health_score": integer,
  "risk_score": integer,
  "missing_clauses": [string],
  "obligations": [string],
  "payment_terms": string|null,
  "parties": [string],
  "auto_tags": [string],
  "action_items": [string],
  "compliance_flags": [string]
}}

Title: {title}

Contract text:
{text}"""

_LIST_FIELDS = (
    "missing_clauses",
    "obligations",
    "parties",
    "auto_tags",
    "action_items",
    "compliance_flags",
)
_STRING_FIELDS = (
    "contract_number",
    "owner",
    "department",
    "vendor",
    "client",
    "currency",
    "effective_date",
    "expiry_date",
    "renewal_date",
    "payment_terms",
)


async def analyze_contract(title: str, text: str = "") -> dict[str, Any]:
    """
    Analyse a contract. Always returns a fully-populated, type-correct dict.

    `analysis_source` is "llm" or "rules" so callers can tell which engine
    produced the numbers.
    """
    body = (text or "").strip()
    if not body:
        logger.info("contract analysis: no extractable text, using rules")
        return _rule_based(title, "")

    try:
        llm = get_llm()
        if llm.name == "extractive":
            # The extractive fallback cannot produce JSON; don't waste the call.
            raise RuntimeError("no generative LLM configured")

        result = await llm.generate(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You extract structured data from contracts and reply "
                        "with raw JSON only."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=_PROMPT.format(title=title, text=body[:_MAX_CHARS]),
                ),
            ],
            temperature=0.0,
            max_tokens=1500,
        )
        parsed = _parse_json(result.text)
        if parsed is None:
            raise ValueError("model did not return parseable JSON")

        analysis = _rule_based(title, body)  # defaults for anything omitted
        analysis.update(_coerce(parsed))
        analysis["analysis_source"] = "llm"
        return analysis
    except Exception as exc:
        logger.warning(
            "contract analysis fell back to rules",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return _rule_based(title, body)


def _parse_json(raw: str) -> dict | None:
    """Tolerate code fences and leading prose around the JSON object."""
    if not raw:
        return None
    cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.MULTILINE)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce(data: dict) -> dict[str, Any]:
    """Force every field into the type the database column expects."""
    out: dict[str, Any] = {}

    for field in _STRING_FIELDS:
        value = data.get(field)
        if isinstance(value, (str, int, float)) and str(value).strip():
            out[field] = str(value).strip()

    for field in _LIST_FIELDS:
        value = data.get(field)
        if isinstance(value, list):
            out[field] = [str(v).strip() for v in value if str(v).strip()]
        elif isinstance(value, str) and value.strip():
            out[field] = [value.strip()]

    value = data.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        out["value"] = float(value)
    elif isinstance(value, str):
        digits = re.sub(r"[^0-9.]", "", value)
        if digits.count(".") <= 1 and digits.strip("."):
            out["value"] = float(digits)

    for field in ("health_score", "risk_score"):
        score = data.get(field)
        if isinstance(score, bool):
            continue
        if isinstance(score, (int, float)):
            out[field] = max(0, min(100, int(score)))
        elif isinstance(score, str) and score.strip().isdigit():
            out[field] = max(0, min(100, int(score.strip())))

    priority = data.get("priority")
    if isinstance(priority, str) and priority.strip().title() in {"High", "Medium", "Low"}:
        out["priority"] = priority.strip().title()

    return out


def _rule_based(title: str, text: str) -> dict[str, Any]:
    """
    Deterministic analysis over the contract text.

    Everything here is derived from what the document actually says: clause
    detection drives the scores, and fields the text does not mention stay null
    rather than being filled with plausible-looking placeholders.
    """
    lowered = text.lower()

    present, missing = [], []
    for clause, keywords in _EXPECTED_CLAUSES.items():
        (present if any(k in lowered for k in keywords) else missing).append(clause)

    coverage = len(present) / len(_EXPECTED_CLAUSES) if text else 0.0
    health = int(round(coverage * 100))
    risk = 100 - health

    return {
        "analysis_source": "rules",
        "contract_number": _first(
            text, r"\b(?:contract|agreement)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9\-/]{3,})"
        ),
        "owner": None,
        "department": None,
        # Case-sensitive on purpose: the leading [A-Z] is what anchors the match
        # to the start of a proper noun rather than mid-sentence.
        "vendor": _first(
            text,
            r'([A-Z][A-Za-z0-9&.,\- ]{2,60}?)\s*\(\s*"?(?:Vendor|Supplier|Provider)"?\s*\)',
            flags=0,
        ),
        "client": _first(
            text,
            r'([A-Z][A-Za-z0-9&.,\- ]{2,60}?)\s*\(\s*"?(?:Client|Customer|Buyer)"?\s*\)',
            flags=0,
        ),
        "value": _money(text),
        "currency": "USD" if ("usd" in lowered or "$" in text) else None,
        "effective_date": _first(
            text,
            r"effective\s+(?:date\s+)?(?:as\s+of\s+)?"
            r"([A-Z][a-z]+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})",
        ),
        "expiry_date": _first(
            text,
            r"(?:expir\w*|terminat\w*|end)\s+(?:on|date)?\s*"
            r"([A-Z][a-z]+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})",
        ),
        "renewal_date": None,
        "priority": "High" if risk >= 50 else "Medium" if risk >= 25 else "Low",
        "health_score": health,
        "risk_score": risk,
        "missing_clauses": missing,
        "obligations": _obligations(text),
        "payment_terms": _first(
            text, r"((?:net\s*\d{1,3}|within\s+\d{1,3}\s+days)[^.\n]{0,120})"
        ),
        "parties": _parties(text),
        "auto_tags": _tags(title, lowered),
        "action_items": [f"Add a {clause} clause" for clause in missing[:5]],
        "compliance_flags": [f"{clause} clause present" for clause in present],
    }


def _first(text: str, pattern: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, text, flags=flags)
    if not match:
        return None
    # Drop a leading connector the pattern may have swept up ("and Acme Ltd").
    return re.sub(r"^(?:and|between|with|by)\s+", "", match.group(1).strip(), flags=re.I)


def _money(text: str) -> float | None:
    """Largest currency amount in the document, usually the contract value."""
    amounts = []
    for raw in re.findall(r"(?:USD|\$)\s*([\d,]+(?:\.\d{1,2})?)", text, flags=re.IGNORECASE):
        try:
            amounts.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return max(amounts) if amounts else None


def _obligations(text: str) -> list[str]:
    """Sentences carrying an obligation verb ("shall", "must", "agrees to")."""
    found = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        clean = " ".join(sentence.split())
        if 25 < len(clean) < 300 and re.search(
            r"\b(shall|must|agrees to|is required to|will provide|undertakes to)\b",
            clean,
            flags=re.IGNORECASE,
        ):
            found.append(clean)
    return found[:8]


def _parties(text: str) -> list[str]:
    """Named entities followed by a defined role, e.g. `Acme Corp ("Client")`."""
    matches = re.findall(
        r'([A-Z][A-Za-z0-9&.,\- ]{2,60}?)\s*\(\s*"?([A-Za-z ]{3,20})"?\s*\)', text
    )
    seen, parties = set(), []
    for name, role in matches:
        entry = f"{name.strip()} ({role.strip().title()})"
        if entry.lower() not in seen:
            seen.add(entry.lower())
            parties.append(entry)
    return parties[:6]


def _tags(title: str, lowered: str) -> list[str]:
    haystack = f"{title.lower()} {lowered}"
    tags = [
        tag
        for tag, keywords in {
            "NDA": ("non-disclosure", "nda", "confidentiality agreement"),
            "SaaS": ("saas", "software as a service", "subscription"),
            "MSA": ("master service", "master agreement", "msa"),
            "SLA": ("service level", "sla", "uptime"),
            "Employment": ("employment", "employee", "salary"),
            "Lease": ("lease", "premises", "landlord"),
        }.items()
        if any(k in haystack for k in keywords)
    ]
    return tags or ["General Agreement"]
