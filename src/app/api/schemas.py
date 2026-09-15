"""Pydantic request/response models for the API."""

from typing import Any

from pydantic import BaseModel


class AdjudicateByPathRequest(BaseModel):
    """Body for POST /v1/claims/adjudicate when not sending a multipart file upload."""

    path: str | None = None
    s3_uri: str | None = None


class RunAuditResponse(BaseModel):
    run_id: str
    document_id: str
    status: str
    decision_json: dict[str, Any]
    total_cost_usd: float
    duration_ms: float
    degraded: bool


class SubgraphResponse(BaseModel):
    seed_codes: list[str]
    hops: int
    triples: list[str]
