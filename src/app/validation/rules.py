"""Business-rule validation for a claims-domain ClaimRecord. Deterministic — no LLM.

Rule codes and their meaning are documented in domains/claims/validation_rules.yaml and in
DEVELOPMENT_PLAN.md > Agent Specifications > ClaimValidatorAgent.
"""

import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml

RULES_PATH = Path(__file__).resolve().parents[3] / "domains" / "claims" / "validation_rules.yaml"


class ValidationIssue(TypedDict):
    field: str
    code: str
    message: str
    severity: Literal["error", "warning"]


class ValidationResult(TypedDict):
    is_valid: bool
    errors: list[ValidationIssue]


@lru_cache(maxsize=1)
def _load_rules_config() -> dict[str, Any]:
    with RULES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _issue(field: str, code: str, message: str) -> ValidationIssue:
    return {"field": field, "code": code, "message": message, "severity": "error"}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def validate_claim(record: dict[str, Any]) -> ValidationResult:
    """Validates a claims-domain extracted-fields dict. Returns every failing rule, not just
    the first — the repair agent (P4) needs the full list to know what to fix."""
    config = _load_rules_config()
    errors: list[ValidationIssue] = []

    for field in config["required_fields"]:
        if not record.get(field):
            msg = f"required field '{field}' is missing or empty"
            errors.append(_issue(field, "REQ_FIELD", msg))

    member_id = record.get("member_id") or ""
    if member_id and not re.match(config["member_id_pattern"], member_id):
        msg = f"'{member_id}' does not match the expected member ID format"
        errors.append(_issue("member_id", "MEMBER_ID_FORMAT", msg))

    icd_pattern = config["icd_code_pattern"]
    for code in record.get("diagnosis_codes") or []:
        if not re.match(icd_pattern, code):
            msg = f"'{code}' is not a valid ICD-10 code"
            errors.append(_issue("diagnosis_codes", "CODE_FORMAT_ICD", msg))

    cpt_pattern = config["cpt_code_pattern"]
    for code in record.get("procedure_codes") or []:
        if not re.match(cpt_pattern, code):
            msg = f"'{code}' is not a valid CPT code"
            errors.append(_issue("procedure_codes", "CODE_FORMAT_CPT", msg))

    start = _parse_date(record.get("service_start_date", ""))
    end = _parse_date(record.get("service_end_date", ""))
    if start and end:
        if end < start:
            msg = "service_end_date is before service_start_date"
            errors.append(_issue("service_end_date", "DATE_ORDER", msg))
        else:
            span_days = (end - start).days
            max_span = config["date_sanity"]["max_service_span_days"]
            in_future = start > date.today() or end > date.today()
            if in_future or span_days > max_span:
                msg = f"service dates must be in the past and within {max_span} days apart"
                errors.append(_issue("service_start_date", "DATE_SANITY", msg))
    elif record.get("service_start_date") or record.get("service_end_date"):
        msg = "service dates are not valid ISO dates"
        errors.append(_issue("service_start_date", "DATE_SANITY", msg))

    claimed_amount = record.get("claimed_amount")
    if claimed_amount is not None and claimed_amount <= 0:
        msg = "claimed_amount must be greater than zero"
        errors.append(_issue("claimed_amount", "AMOUNT_POSITIVE", msg))

    line_items = record.get("line_items") or []
    if claimed_amount is not None and line_items:
        tolerance = config["amount_balance"]["tolerance"]
        line_total = sum(item["amount"] for item in line_items)
        if abs(line_total - claimed_amount) > tolerance:
            msg = f"claimed_amount {claimed_amount} does not match line item sum {line_total}"
            errors.append(_issue("claimed_amount", "AMOUNT_BALANCE", msg))

    policy_no = record.get("policy_no") or ""
    policy_period = config["policy_periods"].get(policy_no)
    if policy_period and start:
        window_start = _parse_date(policy_period["start"])
        window_end = _parse_date(policy_period["end"])
        if window_start and window_end and not (window_start <= start <= window_end):
            errors.append(
                _issue(
                    "service_start_date",
                    "POLICY_WINDOW",
                    f"service date {start} falls outside the policy validity period "
                    f"{policy_period['start']} to {policy_period['end']}",
                )
            )

    return {"is_valid": len(errors) == 0, "errors": errors}


def get_policy_period(policy_no: str) -> dict[str, str] | None:
    """The same small policy/member lookup POLICY_WINDOW uses — PolicyAdjudicatorAgent
    (P6) reuses it to reason about waiting periods (e.g. maternity, pre-existing conditions).
    A production system would call a policy/member service for both."""
    return _load_rules_config()["policy_periods"].get(policy_no)


def is_repairable(errors: list[ValidationIssue]) -> bool:
    """False if any failing rule is in the unrepairable set (e.g. POLICY_WINDOW) — those
    reflect genuinely wrong data, not an OCR problem, and must not be sent to FieldRepairAgent."""
    config = _load_rules_config()
    unrepairable = set(config["unrepairable_rule_codes"])
    codes = {error["code"] for error in errors}
    return not (codes & unrepairable)
