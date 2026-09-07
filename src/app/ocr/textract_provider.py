"""aws: calls AWS Textract AnalyzeDocument (FORMS + TABLES). Never imported at module import
time under APP_ENV=local — boto3 is imported lazily inside analyze().
"""

from pathlib import Path
from typing import Any

from app.core.exceptions import OCRServiceError
from app.observability.metrics import textract_pages_total


class TextractOCRProvider:
    def __init__(self, region: str) -> None:
        self._region = region

    def analyze(self, source_uri: str) -> dict[str, Any]:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client("textract", region_name=self._region)
        document_bytes = Path(source_uri).read_bytes()
        try:
            response = client.analyze_document(
                Document={"Bytes": document_bytes},
                FeatureTypes=["FORMS", "TABLES"],
            )
        except (BotoCoreError, ClientError) as exc:
            textract_pages_total.labels(outcome="error").inc()
            msg = f"Textract AnalyzeDocument failed for '{source_uri}': {exc}"
            raise OCRServiceError(msg) from exc

        pages = response.get("DocumentMetadata", {}).get("Pages", 1)
        textract_pages_total.labels(outcome="success").inc(pages)
        return response
