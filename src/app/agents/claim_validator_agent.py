"""ClaimValidatorAgent — Pydantic + business rule validation. Deterministic. No LLM."""

from typing import Any

from app.agents.base import BaseAgent
from app.validation.rules import ValidationResult, validate_claim


class ClaimValidatorAgent(BaseAgent):
    name = "ClaimValidatorAgent"

    def run(self, extracted_fields: dict[str, Any]) -> ValidationResult:
        return validate_claim(extracted_fields)
