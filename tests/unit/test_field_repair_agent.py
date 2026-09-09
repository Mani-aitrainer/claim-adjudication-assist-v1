from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.agents.claim_validator_agent import ClaimValidatorAgent
from app.agents.field_repair_agent import FieldRepairAgent
from app.ocr.fixture_provider import FixtureOCRProvider

from ..conftest import FakeCopyIntakeLLM, FakeRepairLLM

FIXTURE_DIR = "tests/fixtures/textract"


def _intake(scenario_id: str) -> dict:
    agent = ClaimIntakeAgent(FixtureOCRProvider(FIXTURE_DIR), llm=FakeCopyIntakeLLM())
    return agent.run(f"tests/fixtures/claims/{scenario_id}.pdf")


def test_repair_fixes_char_confusion_and_date_reformat() -> None:
    intake_result = _intake("CLM-006")
    validation = ClaimValidatorAgent().run(intake_result["extracted_fields"])
    assert not validation["is_valid"]

    repaired = FieldRepairAgent(llm=FakeRepairLLM()).run(
        intake_result["ocr_result"], intake_result["extracted_fields"], validation["errors"]
    )
    assert repaired["member_id"] == "MEM1001"
    assert repaired["service_start_date"] == "2024-03-05"

    revalidated = ClaimValidatorAgent().run(repaired)
    assert revalidated["is_valid"]


def test_repair_fixes_noised_currency_line_item() -> None:
    intake_result = _intake("CLM-008")
    validation = ClaimValidatorAgent().run(intake_result["extracted_fields"])
    assert not validation["is_valid"]

    repaired = FieldRepairAgent(llm=FakeRepairLLM()).run(
        intake_result["ocr_result"], intake_result["extracted_fields"], validation["errors"]
    )
    assert repaired["line_items"][1]["amount"] == 800.0

    revalidated = ClaimValidatorAgent().run(repaired)
    assert revalidated["is_valid"]


def test_repair_leaves_dropout_corruption_unchanged() -> None:
    intake_result = _intake("CLM-007")
    validation = ClaimValidatorAgent().run(intake_result["extracted_fields"])

    repaired = FieldRepairAgent(llm=FakeRepairLLM()).run(
        intake_result["ocr_result"], intake_result["extracted_fields"], validation["errors"]
    )
    assert "#" in repaired["member_id"]  # unrecoverable — left as-is, not guessed at

    revalidated = ClaimValidatorAgent().run(repaired)
    assert not revalidated["is_valid"]
