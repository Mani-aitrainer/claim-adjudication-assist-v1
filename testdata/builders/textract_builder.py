"""Emits Textract-shaped JSON directly from a scenario's ground truth, without calling AWS.

BlockType values: PAGE, LINE, WORD, KEY_VALUE_SET (KEY/VALUE), TABLE, CELL — with
Relationships and Confidence scores. Confidence drops on any field that noise was applied
to, which is realistic and gives the HeuristicFallbackAgent a signal to use.
"""

import re
from typing import Any

from testdata.builders.noise import NOISE_FUNCTIONS

CLEAN_CONFIDENCE = 99.0
NOISED_CONFIDENCE = 45.0

_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.(\w+)$")


def _scalar_fields(
    scenario: dict[str, Any], member: dict[str, Any], party: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    """Returns {field_name: (label, raw_value_str)} — what would actually be printed on the form."""
    if scenario["domain"] == "claims":
        return {
            "member_id": ("Member ID", member["member_id"]),
            "policy_no": ("Policy Number", member["policy_no"]),
            "member_age": ("Member Age", str(member["age"])),
            "provider_id": ("Provider ID", party["provider_id"]),
            "provider_name": ("Provider Name", party["name"]),
            "network_status": ("Network Status", party["network_status"]),
            "service_start_date": ("Service Start Date", scenario["service_start_date"]),
            "service_end_date": ("Service End Date", scenario["service_end_date"]),
            "diagnosis_codes": ("Diagnosis Codes", ", ".join(scenario["diagnosis_codes"])),
            "claimed_amount": ("Total Charged", f"{scenario['claimed_amount']:,.2f}"),
            "currency": ("Currency", scenario["currency"]),
        }
    return {
        "member_id": ("Member ID", member["member_id"]),
        "policy_no": ("Policy Number", member["policy_no"]),
        "service_date": ("Invoice Date", scenario["service_date"]),
        "claimed_amount": ("Invoice Total", f"{scenario['claimed_amount']:,.2f}"),
        "currency": ("Currency", scenario["currency"]),
    }


def _apply_scalar_noise(
    value: str, field_name: str, noise_spec: dict[str, str]
) -> tuple[str, float]:
    fn_name = noise_spec.get(field_name)
    if fn_name is None:
        return value, CLEAN_CONFIDENCE
    fn = NOISE_FUNCTIONS[fn_name]
    return str(fn(value)), NOISED_CONFIDENCE


def _line_item_noise_targets(noise_spec: dict[str, str]) -> dict[tuple[int, str], str]:
    targets: dict[tuple[int, str], str] = {}
    for path, fn_name in noise_spec.items():
        match = _LINE_ITEM_PATH.match(path)
        if match:
            targets[(int(match.group(1)), match.group(2))] = fn_name
    return targets


def build_textract_json(
    scenario: dict[str, Any],
    member: dict[str, Any],
    party: dict[str, Any],
) -> dict[str, Any]:
    if scenario.get("simulate_ocr_failure"):
        return {
            "error": {
                "code": "InternalServerError",
                "message": "Textract AnalyzeDocument failed for this document.",
            },
            "meta": {"scenario_id": scenario["id"], "simulate_ocr_failure": True},
        }

    noise_spec: dict[str, str] = scenario.get("noise", {}) or {}
    blocks: list[dict[str, Any]] = []
    lines: list[str] = []
    child_ids: list[str] = ["table-1"]

    blocks.append(
        {
            "BlockType": "PAGE",
            "Id": "page-1",
            "Relationships": [{"Type": "CHILD", "Ids": child_ids}],
        }
    )

    noised_fields: list[str] = []
    for field_name, (label, raw_value) in _scalar_fields(scenario, member, party).items():
        value_text, confidence = _apply_scalar_noise(raw_value, field_name, noise_spec)
        if confidence < CLEAN_CONFIDENCE:
            noised_fields.append(field_name)

        key_id, value_id = f"key-{field_name}", f"value-{field_name}"
        key_word_id, value_word_id = f"{key_id}-word", f"{value_id}-word"
        blocks.extend(
            [
                {
                    "BlockType": "KEY_VALUE_SET",
                    "EntityTypes": ["KEY"],
                    "Id": key_id,
                    "Text": label,
                    "Confidence": CLEAN_CONFIDENCE,
                    "Relationships": [
                        {"Type": "CHILD", "Ids": [key_word_id]},
                        {"Type": "VALUE", "Ids": [value_id]},
                    ],
                },
                {
                    "BlockType": "WORD",
                    "Id": key_word_id,
                    "Text": label,
                    "Confidence": CLEAN_CONFIDENCE,
                },
                {
                    "BlockType": "KEY_VALUE_SET",
                    "EntityTypes": ["VALUE"],
                    "Id": value_id,
                    "Text": value_text,
                    "Confidence": confidence,
                    "Relationships": [{"Type": "CHILD", "Ids": [value_word_id]}],
                    "FieldName": field_name,
                },
                {
                    "BlockType": "WORD",
                    "Id": value_word_id,
                    "Text": value_text,
                    "Confidence": confidence,
                },
            ]
        )
        child_ids.append(key_id)
        lines.append(f"{label}: {value_text}")

    line_item_noise = _line_item_noise_targets(noise_spec)
    table_child_ids: list[str] = []
    header = ["Code", "Description", "Units", "Amount"] if scenario["domain"] == "claims" else [
        "Code", "Description", "Units", "Unit Price", "Amount"
    ]
    for col_idx, header_text in enumerate(header, start=1):
        cell_id = f"cell-0-{col_idx}"
        blocks.append(
            {
                "BlockType": "CELL",
                "Id": cell_id,
                "RowIndex": 0,
                "ColumnIndex": col_idx,
                "Text": header_text,
                "Confidence": CLEAN_CONFIDENCE,
            }
        )
        table_child_ids.append(cell_id)

    for row_idx, item in enumerate(scenario["line_items"], start=1):
        columns = ["code", "description", "units", "amount"]
        if scenario["domain"] != "claims":
            columns = ["code", "description", "units", "unit_price", "amount"]
        row_texts = []
        for col_idx, field in enumerate(columns, start=1):
            raw = item[field]
            fn_name = line_item_noise.get((row_idx - 1, field))
            if fn_name is not None:
                confidence = NOISED_CONFIDENCE
                text = str(NOISE_FUNCTIONS[fn_name](raw))
                noised_fields.append(f"line_items[{row_idx - 1}].{field}")
            else:
                confidence = CLEAN_CONFIDENCE
                text = f"{raw:,.2f}" if field in ("amount", "unit_price") else str(raw)
            cell_id = f"cell-{row_idx}-{col_idx}"
            blocks.append(
                {
                    "BlockType": "CELL",
                    "Id": cell_id,
                    "RowIndex": row_idx,
                    "ColumnIndex": col_idx,
                    "Text": text,
                    "Confidence": confidence,
                }
            )
            table_child_ids.append(cell_id)
            row_texts.append(text)
        lines.append(" | ".join(row_texts))

    blocks.append(
        {
            "BlockType": "TABLE",
            "Id": "table-1",
            "Relationships": [{"Type": "CHILD", "Ids": table_child_ids}],
        }
    )
    for i, text in enumerate(lines):
        blocks.append(
            {"BlockType": "LINE", "Id": f"line-{i}", "Text": text, "Confidence": CLEAN_CONFIDENCE}
        )

    return {
        "DocumentMetadata": {"Pages": 1},
        "Blocks": blocks,
        "meta": {"scenario_id": scenario["id"], "noised_fields": noised_fields},
    }
