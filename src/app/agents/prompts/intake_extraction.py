"""Zero-shot prompt for ClaimIntakeAgent: raw OCR key/value pairs + table rows -> canonical
ClaimRecord fields, returned as strict JSON. domains/claims/field_map.yaml is passed as a
hint list so the model knows which canonical name each printed label should become.
"""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM_PROMPT = """You extract structured claim data from OCR output of a health insurance \
claim form. You are given key/value pairs read from the form and a table of line items. \
Map each key/value pair to its canonical field name using the provided field map as a hint, \
and map the table rows to a `line_items` list. Return ONLY a single strict JSON object with \
these fields: member_id, policy_no, provider_id, provider_name, network_status, \
service_start_date, service_end_date, diagnosis_codes (list of strings), procedure_codes \
(list of strings, taken from the line item codes), line_items (list of \
{code, description, units, amount}), claimed_amount (number), currency. \
Copy values exactly as given — do not correct, reformat, or guess-fix anything, even if a \
value looks malformed. If a field cannot be determined, use an empty string, empty list, or \
0 as appropriate for its type."""


def build_intake_messages(
    key_values: dict[str, Any],
    tables: list[list[dict[str, str]]],
    field_map: dict[str, list[str]],
) -> list[BaseMessage]:
    payload = {
        "field_map_hint": field_map,
        "key_values": {label: field["value"] for label, field in key_values.items()},
        "line_item_table": tables[0] if tables else [],
    }
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, indent=2)),
    ]
