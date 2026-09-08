import json

from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.agents.claim_validator_agent import ClaimValidatorAgent
from app.ocr.fixture_provider import FixtureOCRProvider

from ..conftest import FakeCopyIntakeLLM

FIXTURE_DIR = "tests/fixtures/textract"
CLEAN_CLAIM_SCENARIOS = [
    "CLM-001", "CLM-002", "CLM-003", "CLM-004", "CLM-005",
    "CLM-009", "CLM-010", "CLM-012", "CLM-013",
]


def _extracted_fields(scenario_id: str) -> dict:
    agent = ClaimIntakeAgent(FixtureOCRProvider(FIXTURE_DIR), llm=FakeCopyIntakeLLM())
    return agent.run(f"tests/fixtures/claims/{scenario_id}.pdf")["extracted_fields"]


def test_every_clean_scenario_passes_validation() -> None:
    validator = ClaimValidatorAgent()
    for scenario_id in CLEAN_CLAIM_SCENARIOS:
        result = validator.run(_extracted_fields(scenario_id))
        assert result["is_valid"], f"{scenario_id}: unexpected errors {result['errors']}"


def test_clm006_trips_member_id_format() -> None:
    result = ClaimValidatorAgent().run(_extracted_fields("CLM-006"))
    codes = {error["code"] for error in result["errors"]}
    assert "MEMBER_ID_FORMAT" in codes
    assert not result["is_valid"]


def test_clm007_unrecoverable_noise_fails_validation() -> None:
    result = ClaimValidatorAgent().run(_extracted_fields("CLM-007"))
    assert not result["is_valid"]


def test_clm008_trips_amount_balance() -> None:
    result = ClaimValidatorAgent().run(_extracted_fields("CLM-008"))
    codes = {error["code"] for error in result["errors"]}
    assert "AMOUNT_BALANCE" in codes


def test_clm014_trips_policy_window_and_is_marked_unrepairable() -> None:
    from app.validation.rules import is_repairable

    expected = json.loads(open("tests/fixtures/expected/CLM-014.expected.json").read())
    result = ClaimValidatorAgent().run(expected["ground_truth"])
    codes = {error["code"] for error in result["errors"]}
    assert "POLICY_WINDOW" in codes
    assert not is_repairable(result["errors"])


def test_repairable_rule_codes_are_marked_repairable() -> None:
    from app.validation.rules import is_repairable

    result = ClaimValidatorAgent().run(_extracted_fields("CLM-006"))
    assert is_repairable(result["errors"])


def test_code_format_icd_rejects_malformed_diagnosis_code() -> None:
    from app.validation.rules import validate_claim

    record = {
        "member_id": "MEM1001",
        "policy_no": "POL100001",
        "service_start_date": "2024-03-05",
        "service_end_date": "2024-03-05",
        "diagnosis_codes": ["NOTACODE"],
        "procedure_codes": ["CPT-99213"],
        "line_items": [{"code": "CPT-99213", "description": "x", "units": 1, "amount": 1200}],
        "claimed_amount": 1200,
    }
    result = validate_claim(record)
    assert any(e["code"] == "CODE_FORMAT_ICD" for e in result["errors"])


def test_date_order_rejects_end_before_start() -> None:
    from app.validation.rules import validate_claim

    record = {
        "member_id": "MEM1001",
        "policy_no": "POL100001",
        "service_start_date": "2024-03-10",
        "service_end_date": "2024-03-05",
        "diagnosis_codes": [],
        "procedure_codes": ["CPT-99213"],
        "line_items": [{"code": "CPT-99213", "description": "x", "units": 1, "amount": 1200}],
        "claimed_amount": 1200,
    }
    result = validate_claim(record)
    assert any(e["code"] == "DATE_ORDER" for e in result["errors"])


def test_amount_positive_rejects_zero_claimed_amount() -> None:
    from app.validation.rules import validate_claim

    record = {
        "member_id": "MEM1001",
        "policy_no": "POL100001",
        "service_start_date": "2024-03-05",
        "service_end_date": "2024-03-05",
        "diagnosis_codes": [],
        "procedure_codes": ["CPT-99213"],
        "line_items": [{"code": "CPT-99213", "description": "x", "units": 1, "amount": 0}],
        "claimed_amount": 0,
    }
    result = validate_claim(record)
    assert any(e["code"] == "AMOUNT_POSITIVE" for e in result["errors"])
