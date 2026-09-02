"""Liveness and readiness endpoints.

/healthz has no dependencies. /readyz checks the vector store, cache and secret provider.
"""

from typing import Any

from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    checks: dict[str, str] = {}

    try:
        request.app.state.vector_store.count("claims")
        checks["vector_store"] = "ok"
    except Exception as exc:  # noqa: BLE001 - reported in the readiness payload
        checks["vector_store"] = f"error: {exc}"

    try:
        cache = request.app.state.cache
        cache.set("readyz:probe", "ok", ttl_seconds=5)
        checks["cache"] = "ok" if cache.get("readyz:probe") == "ok" else "error: roundtrip failed"
    except Exception as exc:  # noqa: BLE001
        checks["cache"] = f"error: {exc}"

    settings = request.app.state.settings
    checks["secret"] = "ok" if settings.openai_api_key else "error: OPENAI_API_KEY not set"

    ready = all(value == "ok" for value in checks.values())
    response.status_code = 200 if ready else 503
    return {"status": "ok" if ready else "not_ready", "checks": checks}
