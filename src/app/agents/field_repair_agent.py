"""FieldRepairAgent — few-shot, temp 0.2. Re-extracts failing fields from raw OCR text.

Does not repair genuinely-wrong data: the router (routers.py) only sends repairable rule
codes here — eligibility failures like POLICY_WINDOW go straight to adjudication.
"""

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts.repair_fewshot import build_repair_messages
from app.core.llm_factory import get_llm


class FieldRepairAgent(BaseAgent):
    name = "FieldRepairAgent"

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    def run(
        self,
        ocr_result: dict[str, Any],
        extracted_fields: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        llm = self._llm if self._llm is not None else get_llm("repair_agent")
        messages = build_repair_messages(
            ocr_result["key_values"], ocr_result["tables"], extracted_fields, errors
        )
        response = llm.invoke(messages)
        return dict(json.loads(str(response.content)))
