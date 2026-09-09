from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.agents.heuristic_fallback_agent import HeuristicFallbackAgent
from app.ocr.fixture_provider import FixtureOCRProvider

from ..conftest import FakeCopyIntakeLLM

FIXTURE_DIR = "tests/fixtures/textract"


def test_fallback_flags_for_human_review_and_never_blocks() -> None:
    intake_result = ClaimIntakeAgent(
        FixtureOCRProvider(FIXTURE_DIR), llm=FakeCopyIntakeLLM()
    ).run("tests/fixtures/claims/CLM-007.pdf")

    result = HeuristicFallbackAgent().run(
        intake_result["ocr_result"], intake_result["extracted_fields"]
    )
    assert result["fallback_used"] is True
    assert result["needs_human_review"] is True
    assert result["confidence"] == "low"
    assert result["extraction_source"] == "heuristic_fallback"
    assert result["claimed_amount"]  # recoverable field (untouched by noise) still present
    assert result["member_age"] == 34
    assert isinstance(result["member_age"], int)  # not left as a raw regex-matched string


def test_fallback_handles_missing_ocr_result() -> None:
    result = HeuristicFallbackAgent().run(None, {})
    assert result["fallback_used"] is True
    assert result["needs_human_review"] is True
