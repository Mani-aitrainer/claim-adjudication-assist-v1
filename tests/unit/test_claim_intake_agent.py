from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.cache.memory_cache import InMemoryCache
from app.ocr.fixture_provider import FixtureOCRProvider

from ..conftest import FakeCopyIntakeLLM

FIXTURE_DIR = "tests/fixtures/textract"


def _agent() -> ClaimIntakeAgent:
    return ClaimIntakeAgent(FixtureOCRProvider(FIXTURE_DIR), llm=FakeCopyIntakeLLM())


def test_extracts_clean_claim_correctly() -> None:
    result = _agent().run("tests/fixtures/claims/CLM-001.pdf")
    fields = result["extracted_fields"]
    assert fields["member_id"] == "MEM1001"
    assert fields["policy_no"] == "POL100001"
    assert fields["claimed_amount"] == 1200.0
    assert fields["line_items"][0]["code"] == "CPT-99213"
    assert fields["procedure_codes"] == ["CPT-99213"]
    assert result["extraction_source"] == "intake_llm"


def test_extracts_two_line_claim_correctly() -> None:
    fields = _agent().run("tests/fixtures/claims/CLM-009.pdf")["extracted_fields"]
    assert [item["code"] for item in fields["line_items"]] == ["CPT-99213", "CPT-D2740"]
    assert fields["claimed_amount"] == 6200.0


def test_noised_member_id_is_copied_verbatim_not_corrected() -> None:
    fields = _agent().run("tests/fixtures/claims/CLM-006.pdf")["extracted_fields"]
    assert fields["member_id"] == "MEMIOOI"  # zero-shot doesn't self-correct — that's P4's job


def test_noised_currency_naively_fails_to_parse() -> None:
    fields = _agent().run("tests/fixtures/claims/CLM-008.pdf")["extracted_fields"]
    noised_line = fields["line_items"][1]
    assert noised_line["amount"] == 0.0  # "Rs. 800/-" isn't parseable without a few-shot example
    assert fields["claimed_amount"] == 2000.0  # the clean 'Total Charged' field parses fine


def test_ocr_result_is_cached_by_document_hash() -> None:
    ocr_provider = FixtureOCRProvider(FIXTURE_DIR)
    calls = []
    original_analyze = ocr_provider.analyze

    def counting_analyze(source_uri: str):
        calls.append(source_uri)
        return original_analyze(source_uri)

    ocr_provider.analyze = counting_analyze  # type: ignore[method-assign]
    cache = InMemoryCache()
    agent = ClaimIntakeAgent(ocr_provider, llm=FakeCopyIntakeLLM(), cache=cache)

    agent.run("tests/fixtures/claims/CLM-001.pdf")
    agent.run("tests/fixtures/claims/CLM-001.pdf")

    assert len(calls) == 1  # second run was a cache hit — OCR provider not called again
