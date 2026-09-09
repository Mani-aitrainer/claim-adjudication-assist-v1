"""Few-shot prompt for FieldRepairAgent: four curated raw-OCR-snippet -> corrected-value
examples, one per noise function it needs to undo. Given the failing case's raw key/value
pairs, current extraction and the specific validation errors, it re-extracts just the
failing fields and returns the full corrected canonical JSON.
"""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM_PROMPT = """You repair fields that failed validation after OCR extraction from a \
health insurance claim form. You are given the raw OCR key/value pairs, the current \
(failing) extraction, and the specific validation errors. Re-read the raw OCR text for the \
failing fields and correct them. Four examples of the kind of OCR damage you fix:

Example 1 — digit/letter confusion in an ID:
  raw OCR text: "Member ID: MEMIOOI"
  corrected value: "MEM1001"   (O -> 0, I -> 1)

Example 2 — non-ISO date format:
  raw OCR text: "Service Start Date: 05-Mar-2024"
  corrected value: "2024-03-05"

Example 3 — currency symbols, commas, trailing '/-':
  raw OCR text: "Amount: Rs. 1,200/-"
  corrected value: 1200

Example 4 — line-wrap hyphen and doubled spaces:
  raw OCR text: "Provider Na-\\nme:  City  Care"
  corrected value: "CityCare"

If a field's raw text is too damaged to confidently recover (e.g. mostly '#' characters \
from a smudge), leave it unchanged rather than guessing. Return ONLY a single strict JSON \
object with the same fields as the current extraction: member_id, policy_no, provider_id, \
provider_name, network_status, service_start_date, service_end_date, diagnosis_codes, \
procedure_codes, line_items (list of {code, description, units, amount}), claimed_amount, \
currency."""


def build_repair_messages(
    key_values: dict[str, Any],
    tables: list[list[dict[str, str]]],
    extracted_fields: dict[str, Any],
    errors: list[dict[str, Any]],
) -> list[BaseMessage]:
    payload = {
        "raw_key_values": {label: field["value"] for label, field in key_values.items()},
        "raw_line_item_table": tables[0] if tables else [],
        "current_extraction": extracted_fields,
        "validation_errors": errors,
    }
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, indent=2)),
    ]
