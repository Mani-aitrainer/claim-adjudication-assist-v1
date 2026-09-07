"""local: loads pre-saved Textract JSON fixtures instead of calling AWS."""

import json
from pathlib import Path
from typing import Any

from app.core.exceptions import OCRServiceError
from app.observability.metrics import textract_pages_total


class FixtureOCRProvider:
    def __init__(self, fixture_dir: str | Path) -> None:
        self._fixture_dir = Path(fixture_dir)

    def analyze(self, source_uri: str) -> dict[str, Any]:
        fixture_path = self._fixture_dir / f"{Path(source_uri).stem}.json"
        if not fixture_path.exists():
            raise OCRServiceError(f"no Textract fixture found for '{source_uri}' at {fixture_path}")
        with fixture_path.open("r", encoding="utf-8") as f:
            doc: dict[str, Any] = json.load(f)

        if "error" in doc:
            textract_pages_total.labels(outcome="error").inc()
        else:
            pages = doc.get("DocumentMetadata", {}).get("Pages", 1)
            textract_pages_total.labels(outcome="success").inc(pages)
        return doc
