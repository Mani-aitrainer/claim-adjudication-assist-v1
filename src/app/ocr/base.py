"""OCRProvider protocol: analyze() returns a Textract-shaped document (or its `error` shape).

local -> FixtureOCRProvider (pre-saved Textract JSON). aws -> TextractOCRProvider.
"""

from typing import Any, Protocol


class OCRProvider(Protocol):
    def analyze(self, source_uri: str) -> dict[str, Any]:
        """source_uri is an S3 key (aws) or local path (local) to the document."""
        ...
