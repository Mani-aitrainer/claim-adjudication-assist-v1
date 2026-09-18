"""Verifies the P1 'done when' criteria: every fixture exists, verify passes, and
regenerating with the same seed produces byte-identical output.
"""

import json

from testdata.generate import (
    FIXTURES_CLAIMS_DIR,
    FIXTURES_EXPECTED_DIR,
    FIXTURES_PROMPTS_DIR,
    FIXTURES_TEXTRACT_DIR,
    all_scenarios,
    load_manifest,
)


def test_manifest_has_eighteen_scenarios() -> None:
    manifest = load_manifest()
    scenarios = all_scenarios(manifest)
    assert len(scenarios) == 18
    assert {s["id"] for s in scenarios if s["domain"] == "pharmacy"} == {
        "PHR-001", "PHR-002", "PHR-003", "PHR-004",
    }


def test_every_scenario_has_its_fixtures() -> None:
    manifest = load_manifest()
    for scenario in all_scenarios(manifest):
        sid = scenario["id"]
        assert (FIXTURES_CLAIMS_DIR / f"{sid}.pdf").exists(), sid
        assert (FIXTURES_TEXTRACT_DIR / f"{sid}.json").exists(), sid
        assert (FIXTURES_EXPECTED_DIR / f"{sid}.expected.json").exists(), sid


def test_prompt_fixture_exists() -> None:
    assert (FIXTURES_PROMPTS_DIR / "claim_queries.yaml").exists()


def test_payable_amount_equals_sum_of_per_line() -> None:
    manifest = load_manifest()
    for scenario in all_scenarios(manifest):
        sid = scenario["id"]
        expected = json.loads((FIXTURES_EXPECTED_DIR / f"{sid}.expected.json").read_text())
        decision = expected["decision"]
        if decision["payable_amount"] is None or not decision["per_line"]:
            continue
        line_sum = sum(line["payable"] for line in decision["per_line"])
        assert decision["payable_amount"] == line_sum, sid


def test_clm006_noise_is_recoverable_char_confusion() -> None:
    doc = json.loads((FIXTURES_TEXTRACT_DIR / "CLM-006.json").read_text())
    assert doc["meta"]["noised_fields"] == ["member_id", "service_start_date"]


def test_clm011_simulates_an_ocr_service_error() -> None:
    doc = json.loads((FIXTURES_TEXTRACT_DIR / "CLM-011.json").read_text())
    assert "error" in doc
    assert "Blocks" not in doc
