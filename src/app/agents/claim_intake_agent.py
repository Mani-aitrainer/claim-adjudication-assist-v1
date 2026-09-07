"""ClaimIntakeAgent — Textract OCR -> structured claim fields. Zero-shot, temp 0.0.

Input: source_uri (S3 key or local path). Output: {ocr_result, extracted_fields,
extraction_source}. On an OCR service failure, raises OCRServiceError — the caller
(the graph's intake_node, built in P3/P4) is responsible for routing that to fallback_node.

Cache key: ocr:{sha256(file_bytes)} — Textract bills per page, so this matters (see
DEVELOPMENT_PLAN.md > Caching). Falls back to keying on source_uri itself when the file
can't be read locally (e.g. an S3 key under APP_ENV=aws).
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.agents.base import BaseAgent
from app.agents.prompts.intake_extraction import build_intake_messages
from app.cache.base import CacheProvider
from app.core.llm_factory import get_llm
from app.ocr.base import OCRProvider
from app.ocr.parser import ParsedDocument, parse

FIELD_MAP_PATH = Path(__file__).resolve().parents[3] / "domains" / "claims" / "field_map.yaml"
OCR_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


@lru_cache(maxsize=1)
def _load_field_map() -> dict[str, list[str]]:
    with FIELD_MAP_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ocr_cache_key(source_uri: str) -> str:
    try:
        digest = hashlib.sha256(Path(source_uri).read_bytes()).hexdigest()
    except OSError:
        digest = hashlib.sha256(source_uri.encode("utf-8")).hexdigest()
    return f"ocr:{digest}"


class IntakeResult(dict[str, Any]):
    """{ocr_result, extracted_fields, extraction_source}."""


class ClaimIntakeAgent(BaseAgent):
    name = "ClaimIntakeAgent"

    def __init__(
        self,
        ocr_provider: OCRProvider,
        llm: Any | None = None,
        cache: CacheProvider | None = None,
    ) -> None:
        self._ocr_provider = ocr_provider
        self._llm = llm
        self._cache = cache

    def run(self, source_uri: str) -> IntakeResult:
        if self._cache is not None:
            doc = self._cache.get_or_set(
                _ocr_cache_key(source_uri),
                OCR_CACHE_TTL_SECONDS,
                lambda: self._ocr_provider.analyze(source_uri),
            )
        else:
            doc = self._ocr_provider.analyze(source_uri)
        parsed = parse(doc)
        extracted_fields = self._map_to_canonical(parsed)
        return IntakeResult(
            ocr_result=parsed,
            extracted_fields=extracted_fields,
            extraction_source="intake_llm",
        )

    def _map_to_canonical(self, parsed: ParsedDocument) -> dict[str, Any]:
        llm = self._llm if self._llm is not None else get_llm("intake_agent")
        messages = build_intake_messages(parsed["key_values"], parsed["tables"], _load_field_map())
        response = llm.invoke(messages)
        return json.loads(str(response.content))
