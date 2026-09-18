"""Shared test infrastructure: scripted LLM/embeddings doubles standing in for every
get_llm(...) / get_embeddings_client() call, plus the fixtures built on top of them
(ingested policy graph/vector store, fixture OCR, temp-sqlite settings). Every one of
these doubles reads only what the real prompt would give it (or, for FakeGraphExtractionLLM,
the clause text itself) — never testdata/seeds directly — so they stay honest stand-ins for
"what a well-behaved LLM call would return", not answer keys. No test in this suite makes a
network call.
"""

import ast
import copy
import json
import re
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.settings import Settings
from app.ocr.fixture_provider import FixtureOCRProvider
from app.rag.graph_store import PolicyGraphStore
from app.rag.vector_store import VectorStore, get_vector_store
from pipelines import data_pipeline

POLICY_DIR = Path("data/policies")
TEXTRACT_FIXTURE_DIR = "tests/fixtures/textract"

# ---------------------------------------------------------------------------
# get_llm("intake_agent") — copies raw OCR text verbatim into canonical fields via
# field_map aliases, with a naive number parser (deliberately unable to normalise
# currency-symbol noise — that recovery is FieldRepairAgent's job, via few-shot examples).
# ---------------------------------------------------------------------------


def _naive_number(text: str) -> float:
    try:
        return float(text.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def _naive_int(text: str) -> int:
    try:
        return int(float(text.replace(",", "")))
    except (ValueError, AttributeError):
        return 0


class FakeCopyIntakeLLM:
    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        payload = json.loads(messages[-1].content)
        key_values: dict[str, str] = payload["key_values"]
        field_map: dict[str, list[str]] = payload["field_map_hint"]
        rows: list[dict[str, str]] = payload["line_item_table"]

        result: dict[str, Any] = {}
        for canonical, labels in field_map.items():
            value = ""
            for label in labels:
                if label in key_values:
                    value = key_values[label]
                    break
            result[canonical] = value

        result["diagnosis_codes"] = [
            c.strip() for c in result.get("diagnosis_codes", "").split(",") if c.strip()
        ]
        result["claimed_amount"] = _naive_number(result.get("claimed_amount", ""))
        if "member_age" in result:
            result["member_age"] = _naive_int(result["member_age"])

        line_items = []
        procedure_codes = []
        for row in rows:
            code = row.get("Code", "")
            procedure_codes.append(code)
            line_items.append(
                {
                    "code": code,
                    "description": row.get("Description", ""),
                    "units": _naive_int(row.get("Units", "0")),
                    "amount": _naive_number(row.get("Amount", "0")),
                }
            )
        result["line_items"] = line_items
        result["procedure_codes"] = procedure_codes

        return SimpleNamespace(content=json.dumps(result))


# ---------------------------------------------------------------------------
# get_llm("repair_agent") — reverses the noise patterns testdata/builders/noise.py
# applies, only for fields the validator actually flagged. Leaves '#' (dropout/smudge)
# corruption untouched — that's designed to be unrecoverable.
# ---------------------------------------------------------------------------

_LETTER_TO_DIGIT = {"O": "0", "I": "1", "S": "5", "B": "8"}
_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}
_NON_ISO_DATE = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _fix_id(value: str) -> str:
    if "#" in value:
        return value
    return "".join(_LETTER_TO_DIGIT.get(ch, ch) for ch in value)


def _fix_date(value: str) -> str:
    if "#" in value or _ISO_DATE.match(value):
        return value
    match = _NON_ISO_DATE.match(value)
    if match:
        day, month_name, year = match.groups()
        return f"{year}-{_MONTHS.get(month_name, '01')}-{day}"
    return value


def _fix_amount(value: Any) -> Any:
    if isinstance(value, int | float):
        return value
    text = str(value)
    if "#" in text:
        return value
    cleaned = (
        text.replace("Rs.", "").replace("Rs", "").replace("₹", "")
        .replace("/-", "").replace(",", "").strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return value


class FakeRepairLLM:
    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        payload = json.loads(messages[-1].content)
        corrected = copy.deepcopy(payload["current_extraction"])
        error_fields = {error["field"] for error in payload["validation_errors"]}

        if "member_id" in error_fields:
            corrected["member_id"] = _fix_id(corrected["member_id"])
        if "policy_no" in error_fields:
            corrected["policy_no"] = _fix_id(corrected["policy_no"])
        for date_field in ("service_start_date", "service_end_date"):
            if date_field in error_fields:
                corrected[date_field] = _fix_date(corrected[date_field])

        if "claimed_amount" in error_fields:
            corrected["claimed_amount"] = _fix_amount(corrected["claimed_amount"])
            raw_rows = payload.get("raw_line_item_table") or []
            if raw_rows and len(raw_rows) == len(corrected.get("line_items", [])):
                for item, raw_row in zip(corrected["line_items"], raw_rows, strict=True):
                    if "Amount" in raw_row:
                        item["amount"] = _fix_amount(raw_row["Amount"])

        return SimpleNamespace(content=json.dumps(corrected))


# ---------------------------------------------------------------------------
# get_embeddings_client() — deterministic hashing-trick bag-of-words vectorizer (real
# enough that cosine similarity meaningfully ranks results). crc32, not hash(), because
# Python's built-in hash() is randomised per process (PYTHONHASHSEED).
# ---------------------------------------------------------------------------

_VECTOR_DIM = 1536  # matches config/agents.yaml's embedding.dimensions
_WORD_RE = re.compile(r"[a-z]+")


def _stable_hash(word: str) -> int:
    return zlib.crc32(word.encode("utf-8"))


class FakeEmbeddingsClient:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        vector = [0.0] * _VECTOR_DIM
        for word in _WORD_RE.findall(text.lower()):
            vector[_stable_hash(word) % _VECTOR_DIM] += 1.0
        return vector


# ---------------------------------------------------------------------------
# get_llm("graph_extraction") — reads the clause text itself and derives numeric-detail
# edges via regex. A benefit's own sub-limit attaches to the clause node; a policy-wide
# condition (co-pay by age, out-of-network reimbursement) attaches to a constant "POLICY"
# node instead, so it surfaces for every claim regardless of which procedure code seeds
# the graph traversal.
# ---------------------------------------------------------------------------

_SUB_LIMIT = re.compile(r"sub-limit of inr ([\d,]+)")
_ANNUAL_LIMIT = re.compile(r"annual sub-limit of inr ([\d,]+)")
_COPAY = re.compile(r"co-payment of (\d+)%")
_MIN_AGE = re.compile(r"aged (\d+) years")
_REIMBURSE = re.compile(r"reimbursed at (\d+)%")
_WAITING = re.compile(r"waiting period of (\d+) months")
_CLAUSE_ID = re.compile(r"\[Clause ([A-Z]{2}-\d+\.\d+)\]")


class FakeGraphExtractionLLM:
    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        text = messages[-1].content
        clause_match = _CLAUSE_ID.search(text)
        clause_id = clause_match.group(1) if clause_match else "UNKNOWN"
        lower = re.sub(r"\s+", " ", text.lower())  # PDF line wraps can split words onto lines
        node_type = "Exclusion" if "excluded from coverage" in lower else "Benefit"
        edges: list[dict[str, Any]] = []

        own_limit_props = {}
        if match := _SUB_LIMIT.search(lower):
            own_limit_props["sub_limit_inr"] = int(match.group(1).replace(",", ""))
        if match := _ANNUAL_LIMIT.search(lower):
            own_limit_props["annual_sub_limit_inr"] = int(match.group(1).replace(",", ""))
        if own_limit_props:
            edges.append(
                {
                    "src": clause_id,
                    "src_type": node_type,
                    "relation": "has_sublimit",
                    "dst": f"{clause_id}-limit",
                    "dst_type": "SubLimit",
                    "clause_id": clause_id,
                    "properties": own_limit_props,
                }
            )

        condition_props = {}
        if match := _COPAY.search(lower):
            condition_props["copay_percent"] = int(match.group(1))
            if age_match := _MIN_AGE.search(lower):
                condition_props["min_age"] = int(age_match.group(1))
        if match := _REIMBURSE.search(lower):
            condition_props["reimbursement_percent"] = int(match.group(1))
        if condition_props:
            edges.append(
                {
                    "src": "POLICY",
                    "src_type": "Policy",
                    "relation": "applies_to",
                    "dst": f"{clause_id}-limit",
                    "dst_type": "SubLimit",
                    "clause_id": clause_id,
                    "properties": condition_props,
                }
            )

        if match := _WAITING.search(lower):
            edges.append(
                {
                    "src": clause_id,
                    "src_type": node_type,
                    "relation": "requires_waiting",
                    "dst": f"{clause_id}-wait",
                    "dst_type": "WaitingPeriod",
                    "clause_id": clause_id,
                    "properties": {"months": int(match.group(1))},
                }
            )

        return SimpleNamespace(content=json.dumps(edges))


# ---------------------------------------------------------------------------
# get_llm("adjudicator_agent") — implements the six-step CoT reasoning the real prompt
# asks a model to perform, reading only graph triples, vector chunks, claim fields, policy
# inception date and prior-decision memory facts (exactly what the prompt provides).
# ---------------------------------------------------------------------------

_CLAUSE_SUFFIX = re.compile(r"  \[clause: (\S+)\]$")
_TRIPLE = re.compile(r"^(\S+) —(\w+)→ (\S+)(?: (\{.*\}))?$")

ParsedTriple = tuple[str, str, str, dict[str, Any], str | None]


def _parse_triple(triple: str) -> ParsedTriple:
    clause_match = _CLAUSE_SUFFIX.search(triple)
    clause_id = clause_match.group(1) if clause_match else None
    core = triple[: clause_match.start()] if clause_match else triple
    match = _TRIPLE.match(core)
    if not match:
        return core, "", "", {}, clause_id
    src, relation, dst, props_str = match.groups()
    properties = ast.literal_eval(props_str) if props_str else {}
    return src, relation, dst, properties, clause_id


def _months_between(start_iso: str, end_iso: str) -> int:
    y1, m1, d1 = (int(part) for part in start_iso.split("-"))
    y2, m2, d2 = (int(part) for part in end_iso.split("-"))
    months = (y2 - y1) * 12 + (m2 - m1)
    if d2 < d1:
        months -= 1
    return months


class FakeAdjudicatorLLM:
    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        payload = json.loads(messages[-1].content)
        claim = payload["claim"]
        policy_inception = payload.get("policy_inception_date")
        policy_expiry = payload.get("policy_expiry_date")
        triples = [_parse_triple(t) for t in payload.get("graph_triples", [])]

        service_date = claim.get("service_start_date")
        if policy_inception and policy_expiry and service_date:
            if not (policy_inception <= service_date <= policy_expiry):
                per_line = [
                    {"code": item["code"], "claimed": item["amount"], "payable": 0,
                     "reason": "service date outside the policy validity period",
                     "clause_id": None}
                    for item in claim.get("line_items", [])
                ]
                decision = {
                    "status": "DENY",
                    "payable_amount": 0,
                    "currency": claim.get("currency", "INR"),
                    "per_line": per_line,
                    "rationale": "service date falls outside the policy validity period",
                    "citations": [],
                }
                payload_out = {
                    "decision": decision,
                    "reasoning_trace": "Step 1: ineligible.",
                }
                return SimpleNamespace(content=json.dumps(payload_out))

        copay_percent = 0
        network_percent = 100
        citations: set[str] = set()

        for src, relation, _dst, props, clause_id in triples:
            if src != "POLICY" or relation != "applies_to":
                continue
            if "copay_percent" in props and claim.get("member_age", 0) >= props.get("min_age", 0):
                copay_percent = props["copay_percent"]
                if clause_id:
                    citations.add(clause_id)
            if "reimbursement_percent" in props and claim.get("network_status") == "out_of_network":
                network_percent = props["reimbursement_percent"]
                if clause_id:
                    citations.add(clause_id)

        per_line = []
        for item in claim.get("line_items", []):
            code, claimed = item["code"], item["amount"]
            code_edge = next(
                (t for t in triples if t[0] == code and t[1] in ("maps_to", "excludes")), None
            )
            if code_edge is None:
                per_line.append(
                    {"code": code, "claimed": claimed, "payable": 0,
                     "reason": "no matching benefit found in retrieved context", "clause_id": None}
                )
                continue

            _, relation, benefit_clause, _, clause_id = code_edge
            if relation == "excludes":
                per_line.append(
                    {"code": code, "claimed": claimed, "payable": 0,
                     "reason": "excluded from coverage", "clause_id": clause_id}
                )
                if clause_id:
                    citations.add(clause_id)
                continue

            wait_edge = next(
                (t for t in triples if t[0] == benefit_clause and t[1] == "requires_waiting"), None
            )
            if wait_edge and policy_inception:
                months_required = wait_edge[3].get("months", 0)
                served = _months_between(policy_inception, claim["service_start_date"])
                if served < months_required:
                    per_line.append(
                        {"code": code, "claimed": claimed, "payable": 0,
                         "reason": "waiting period not yet served", "clause_id": benefit_clause}
                    )
                    citations.add(benefit_clause)
                    continue

            payable = float(claimed)
            sublimit_edge = next(
                (t for t in triples if t[0] == benefit_clause and t[1] == "has_sublimit"), None
            )
            if sublimit_edge:
                limit = sublimit_edge[3].get("sub_limit_inr") or sublimit_edge[3].get(
                    "annual_sub_limit_inr"
                )
                if limit is not None:
                    payable = min(payable, float(limit))
            if copay_percent:
                payable = payable * (100 - copay_percent) / 100
            if network_percent < 100:
                payable = payable * network_percent / 100
            citations.add(benefit_clause)

            per_line.append(
                {"code": code, "claimed": claimed, "payable": payable,
                 "reason": "covered", "clause_id": benefit_clause}
            )

        total_claimed = sum(item["amount"] for item in claim.get("line_items", []))
        total_payable = sum(line["payable"] for line in per_line)
        if total_payable <= 0:
            status = "DENY"
        elif total_payable < total_claimed:
            status = "PARTIAL"
        else:
            status = "APPROVE"

        is_duplicate = any(
            fact.get("service_start_date") == claim.get("service_start_date")
            and fact.get("service_end_date") == claim.get("service_end_date")
            and fact.get("claimed_amount") == claim.get("claimed_amount")
            for fact in payload.get("memory", [])
        )
        if is_duplicate:
            status = "MANUAL_REVIEW"

        decision = {
            "status": status,
            "payable_amount": total_payable,
            "currency": claim.get("currency", "INR"),
            "per_line": per_line,
            "rationale": "computed from retrieved graph triples per the six-step CoT",
            "citations": sorted(citations),
        }
        reasoning_trace = (
            f"Step 1-6: computed status={status} payable={total_payable} "
            f"citations={sorted(citations)} from the retrieved graph triples."
        )
        return SimpleNamespace(
            content=json.dumps({"decision": decision, "reasoning_trace": reasoning_trace})
        )


# ---------------------------------------------------------------------------
# get_llm("auditor_agent") — always reports a high score; the point of this fake is to
# prove the *deterministic* checks and heal-loop wiring work. DecisionAuditorAgent itself
# caps the score at 0.5 when a deterministic check fails, regardless of what the LLM says.
# ---------------------------------------------------------------------------


class FakeAuditLLM:
    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        return SimpleNamespace(
            content=json.dumps({"quality_score": 0.95, "issues": [], "suggested_fix": ""})
        )


class FlakyOnceAdjudicatorLLM:
    """Wraps a real adjudicator fake but corrupts its first response with a citation not
    present in the retrieved context — standing in for a model that needs one nudge to
    ground its answer properly. Used only by the CLM-012 heal-loop test."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._call_count = 0

    def invoke(self, messages: list[Any]) -> SimpleNamespace:
        self._call_count += 1
        response = self._inner.invoke(messages)
        if self._call_count > 1:
            return response
        result = json.loads(response.content)
        result["decision"]["citations"].append("EX-7.1")  # not in this claim's context
        return SimpleNamespace(content=json.dumps(result))


# ---------------------------------------------------------------------------
# Fixtures: the ingested policy graph/vector store (session-scoped — ingesting once and
# reusing is the same for every test that needs it), fixture OCR, temp-sqlite settings.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rag_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp_path = tmp_path_factory.mktemp("rag")
    settings = Settings(vector_backend="numpy", documents_dir=str(tmp_path / "documents"))
    data_pipeline.ingest(
        POLICY_DIR,
        "claims",
        True,
        settings,
        embeddings_client=FakeEmbeddingsClient(),
        graph_llm=FakeGraphExtractionLLM(),
    )
    return settings


@pytest.fixture(scope="session")
def graph_store(rag_settings: Settings) -> PolicyGraphStore:
    store = PolicyGraphStore()
    store.load(data_pipeline.graph_pickle_path(rag_settings))
    return store


@pytest.fixture(scope="session")
def vector_store(rag_settings: Settings) -> VectorStore:
    return get_vector_store(rag_settings)


@pytest.fixture
def fixture_ocr_provider() -> FixtureOCRProvider:
    return FixtureOCRProvider(TEXTRACT_FIXTURE_DIR)


@pytest.fixture
def temp_sqlite_settings(tmp_path: Path) -> Settings:
    """A Settings instance pointed at a fresh, per-test SQLite file and a numpy vector
    backend — the fast, zero-Docker, zero-network configuration every test should use
    unless it specifically wants the real Postgres path."""
    return Settings(
        vector_backend="numpy",
        documents_dir=str(tmp_path / "documents"),
        sqlite_path=str(tmp_path / "checkpoints.sqlite"),
        fixture_dir=TEXTRACT_FIXTURE_DIR,
    )
