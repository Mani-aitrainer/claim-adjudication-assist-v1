"""HeuristicFallbackAgent — regex/positional heuristics over raw_text. Deterministic, no LLM.

Last-resort extraction when FieldRepairAgent is exhausted (or intake failed outright).
Fills whatever it can, flags for human review, and always continues — a clearly-marked
degraded decision is more useful than a hard failure.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.agents.base import BaseAgent

FIELD_MAP_PATH = Path(__file__).resolve().parents[3] / "domains" / "claims" / "field_map.yaml"

_NUMERIC_FIELDS = {"member_age"}


@lru_cache(maxsize=1)
def _load_field_map() -> dict[str, list[str]]:
    with FIELD_MAP_PATH.open("r", encoding="utf-8") as f:
        return dict(yaml.safe_load(f))


class HeuristicFallbackAgent(BaseAgent):
    name = "HeuristicFallbackAgent"

    def run(
        self, ocr_result: dict[str, Any] | None, extracted_fields: dict[str, Any]
    ) -> dict[str, Any]:
        result = dict(extracted_fields)
        raw_text = ocr_result["raw_text"] if ocr_result else ""
        field_map = _load_field_map()

        for canonical, labels in field_map.items():
            for label in labels:
                match = re.search(rf"{re.escape(label)}:\s*(.+)", raw_text)
                if not match:
                    continue
                value = match.group(1).strip()
                if canonical in _NUMERIC_FIELDS:
                    try:
                        result[canonical] = int(value)
                    except ValueError:
                        continue
                    break
                result[canonical] = value
                break

        result["fallback_used"] = True
        result["needs_human_review"] = True
        result["confidence"] = "low"
        result["extraction_source"] = "heuristic_fallback"
        return result
