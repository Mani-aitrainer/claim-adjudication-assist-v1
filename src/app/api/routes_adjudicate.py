"""POST /v1/claims/adjudicate — multipart upload or {"path" | "s3_uri"}, SSE stream.

graph.astream_events maps to our own named SSE events. "token" events are a deliberate
simplification: our agents call the LLM with a single invoke(), not a streaming call, so
there is no real token-by-token signal to relay — we chunk the adjudicator's finished
reasoning_trace into pieces instead, to demonstrate the event shape a real streaming LLM
call would produce.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from starlette.datastructures import UploadFile

NODE_NAMES = {"intake", "validate", "repair", "fallback", "adjudicate", "audit"}
TOKEN_CHUNK_CHARS = 40
KEEPALIVE_SECONDS = 15

router = APIRouter(prefix="/v1/claims", tags=["claims"])


async def _read_document(request: Request) -> tuple[bytes, str]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form["file"]
        if not isinstance(upload, UploadFile):
            raise ValueError("'file' field must be a file upload")
        return await upload.read(), upload.filename or "upload.pdf"

    body = await request.json()
    path = body.get("path") or body.get("s3_uri")
    if not path:
        raise ValueError("request body must include 'path' or 's3_uri'")
    return Path(path).read_bytes(), Path(path).name


@router.post("/adjudicate")
async def adjudicate(request: Request) -> EventSourceResponse:
    settings = request.app.state.settings
    graph = request.app.state.graph
    checkpointer = request.app.state.checkpointer
    run_audit_store = request.app.state.run_audit_store

    content, filename = await _read_document(request)
    run_id = str(uuid.uuid4())
    # a per-run subdirectory (not a run_id-prefixed filename) keeps the original filename
    # stem intact — FixtureOCRProvider looks fixtures up by that stem
    dest = Path(settings.documents_dir) / run_id / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    async def event_generator() -> Any:
        config = {"configurable": {"thread_id": run_id}}
        initial_state = {"run_id": run_id, "source_uri": str(dest), "domain": "claims"}
        start = time.perf_counter()

        try:
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                name = event.get("name")
                if name not in NODE_NAMES:
                    continue

                if event["event"] == "on_chain_start":
                    yield {
                        "event": "node_start",
                        "data": json.dumps({"agent": name, "ts": time.time()}),
                    }
                    continue

                if event["event"] != "on_chain_end":
                    continue

                output = event["data"].get("output") or {}
                latency_ms = (time.perf_counter() - start) * 1000
                yield {
                    "event": "node_end",
                    "data": json.dumps({"agent": name, "latency_ms": round(latency_ms, 1)}),
                }

                if name == "validate" and "validation" in output:
                    yield {"event": "validation", "data": json.dumps(output["validation"])}
                elif name == "repair":
                    fixed = list((output.get("extracted_fields") or {}).keys())
                    payload = {"attempt": output.get("retry_count"), "fields_fixed": fixed}
                    yield {"event": "repair", "data": json.dumps(payload)}
                elif name == "audit" and output.get("critique"):
                    payload = {
                        "attempt": output.get("heal_attempts"),
                        "quality_score": output.get("quality_score"),
                    }
                    yield {"event": "healing", "data": json.dumps(payload)}
                elif name == "adjudicate" and output.get("reasoning_trace"):
                    trace = output["reasoning_trace"]
                    for i in range(0, len(trace), TOKEN_CHUNK_CHARS):
                        chunk = trace[i : i + TOKEN_CHUNK_CHARS]
                        payload = {"agent": "PolicyAdjudicatorAgent", "delta": chunk}
                        yield {"event": "token", "data": json.dumps(payload)}

            checkpoint_tuple = await checkpointer.aget_tuple(config)
            final_state = checkpoint_tuple.checkpoint["channel_values"] if checkpoint_tuple else {}
            decision = final_state.get("decision", {})
            degraded = final_state.get("degraded", False)
            duration_ms = (time.perf_counter() - start) * 1000

            run_audit_store.write_run(
                run_id=run_id,
                document_id=filename,
                status=decision.get("status", "UNKNOWN"),
                decision_json=decision,
                total_cost_usd=0.0,
                duration_ms=duration_ms,
                degraded=degraded,
            )
            yield {
                "event": "final",
                "data": json.dumps(
                    {"run_id": run_id, "decision": decision, "cost_usd": 0.0, "degraded": degraded}
                ),
            }
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an SSE event
            yield {"event": "error", "data": json.dumps({"run_id": run_id, "message": str(exc)})}

    return EventSourceResponse(
        event_generator(),
        ping=KEEPALIVE_SECONDS,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
