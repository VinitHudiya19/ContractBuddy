"""
Contract analysis tests.

The suite runs without an API key, so these exercise the deterministic
rule-based path plus the parsing/coercion layer that guards whatever an LLM
returns. The central assertion is that the output reflects the actual document:
the previous implementation returned the same invented values for every upload.
"""
from __future__ import annotations

from app.services.contract_analysis import _coerce, _parse_json, analyze_contract

_FULL_CONTRACT = """
MASTER SERVICES AGREEMENT
Between Stark Industries ("Client") and Wayne Logistics LLC ("Vendor").
1. PAYMENT. Client shall pay USD 250,000 within Net 45 days of invoice.
2. TERMINATION. Either party may terminate on 90 days notice.
3. CONFIDENTIALITY. Both parties shall protect confidential information.
4. LIABILITY. Vendor liability is limited to fees paid.
5. GOVERNING LAW. Governed by the laws of New York.
6. DISPUTE RESOLUTION. Disputes resolved by binding arbitration.
7. DATA PROTECTION. Parties comply with GDPR for personal data.
8. INTELLECTUAL PROPERTY. Ownership of deliverables transfers on payment.
9. SERVICE LEVELS. Vendor guarantees 99.9% uptime.
10. FORCE MAJEURE. Neither party is liable for events beyond its control.
"""

_SPARSE_CONTRACT = """
LETTER OF INTENT
Acme Ltd intends to purchase widgets from Globex.
The parties will negotiate final terms at a later date.
"""


class TestRuleBasedAnalysis:
    async def test_extracts_parties_and_value_from_the_text(self):
        result = await analyze_contract("MSA", _FULL_CONTRACT)
        assert result["analysis_source"] == "rules"
        assert result["vendor"] == "Wayne Logistics LLC"
        assert result["client"] == "Stark Industries"
        assert result["value"] == 250_000.0
        assert "Net 45" in result["payment_terms"]

    async def test_complete_contract_scores_better_than_sparse_one(self):
        full = await analyze_contract("MSA", _FULL_CONTRACT)
        sparse = await analyze_contract("LOI", _SPARSE_CONTRACT)

        assert full["health_score"] > sparse["health_score"]
        assert full["risk_score"] < sparse["risk_score"]
        assert len(full["missing_clauses"]) < len(sparse["missing_clauses"])

    async def test_scores_are_complementary_and_in_range(self):
        result = await analyze_contract("MSA", _FULL_CONTRACT)
        assert 0 <= result["health_score"] <= 100
        assert 0 <= result["risk_score"] <= 100
        assert result["health_score"] + result["risk_score"] == 100

    async def test_missing_clauses_reflect_what_is_absent(self):
        result = await analyze_contract("LOI", _SPARSE_CONTRACT)
        assert "Termination" in result["missing_clauses"]
        assert "Confidentiality" in result["missing_clauses"]

    async def test_obligations_come_from_sentences_in_the_document(self):
        result = await analyze_contract("MSA", _FULL_CONTRACT)
        assert result["obligations"]
        for obligation in result["obligations"]:
            assert obligation in " ".join(_FULL_CONTRACT.split())

    async def test_different_documents_produce_different_analyses(self):
        first = await analyze_contract("MSA", _FULL_CONTRACT)
        second = await analyze_contract("LOI", _SPARSE_CONTRACT)
        assert first != second
        assert first["health_score"] != second["health_score"]

    async def test_empty_text_does_not_invent_values(self):
        result = await analyze_contract("Untitled", "")
        assert result["value"] is None
        assert result["vendor"] is None
        assert result["health_score"] == 0

    async def test_tags_are_derived_from_content(self):
        nda = await analyze_contract("Mutual NDA", "This non-disclosure agreement...")
        assert "NDA" in nda["auto_tags"]


class TestLLMResponseParsing:
    def test_parses_plain_json(self):
        assert _parse_json('{"health_score": 90}') == {"health_score": 90}

    def test_strips_markdown_code_fences(self):
        raw = '```json\n{"health_score": 80}\n```'
        assert _parse_json(raw) == {"health_score": 80}

    def test_recovers_json_embedded_in_prose(self):
        raw = 'Here is the analysis:\n{"risk_score": 25}\nHope that helps!'
        assert _parse_json(raw) == {"risk_score": 25}

    def test_returns_none_for_unparseable_output(self):
        assert _parse_json("I cannot analyse this document.") is None
        assert _parse_json("") is None

    def test_rejects_a_bare_json_list(self):
        assert _parse_json("[1, 2, 3]") is None


class TestFieldCoercion:
    def test_numeric_string_becomes_a_float(self):
        assert _coerce({"value": "$1,250.50"})["value"] == 1250.50

    def test_scores_are_clamped_to_range(self):
        assert _coerce({"health_score": 150})["health_score"] == 100
        assert _coerce({"risk_score": -20})["risk_score"] == 0

    def test_numeric_string_score_is_accepted(self):
        assert _coerce({"health_score": "72"})["health_score"] == 72

    def test_string_is_wrapped_into_a_list_field(self):
        assert _coerce({"obligations": "Deliver monthly"})["obligations"] == [
            "Deliver monthly"
        ]

    def test_blank_and_missing_values_are_dropped(self):
        coerced = _coerce({"vendor": "   ", "client": None})
        assert "vendor" not in coerced
        assert "client" not in coerced

    def test_invalid_priority_is_ignored(self):
        assert "priority" not in _coerce({"priority": "URGENT!!"})
        assert _coerce({"priority": "high"})["priority"] == "High"

    def test_booleans_are_not_treated_as_scores(self):
        assert "health_score" not in _coerce({"health_score": True})
