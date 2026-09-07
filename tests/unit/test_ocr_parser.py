import json

import pytest

from app.core.exceptions import OCRServiceError
from app.ocr.parser import parse

FIXTURE_DIR = "tests/fixtures/textract"


def _load(scenario_id: str) -> dict:
    with open(f"{FIXTURE_DIR}/{scenario_id}.json", encoding="utf-8") as f:
        return json.load(f)


def test_parses_clean_claim_into_key_values_and_table() -> None:
    parsed = parse(_load("CLM-001"))
    assert parsed["key_values"]["Member ID"]["value"] == "MEM1001"
    assert parsed["key_values"]["Member ID"]["confidence"] == 99.0
    assert len(parsed["tables"]) == 1
    assert parsed["tables"][0][0]["Code"] == "CPT-99213"
    assert "Member ID: MEM1001" in parsed["raw_text"]


def test_noised_field_has_low_confidence() -> None:
    parsed = parse(_load("CLM-006"))
    assert parsed["key_values"]["Member ID"]["value"] == "MEMIOOI"
    assert parsed["key_values"]["Member ID"]["confidence"] < 60.0


def test_ocr_service_failure_raises() -> None:
    with pytest.raises(OCRServiceError):
        parse(_load("CLM-011"))


def test_multi_line_table_preserves_row_order() -> None:
    parsed = parse(_load("CLM-009"))
    codes = [row["Code"] for row in parsed["tables"][0]]
    assert codes == ["CPT-99213", "CPT-D2740"]
