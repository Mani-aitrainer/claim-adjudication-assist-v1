"""GET /v1/runs/{run_id}, GET /v1/runs/{run_id}/state, POST /v1/runs/{run_id}/resume."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.graph.build_graph import run_graph

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    record = request.app.state.run_audit_store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no run_audit record for '{run_id}'")
    return record


@router.get("/{run_id}/state")
async def get_run_state(run_id: str, request: Request) -> dict[str, Any]:
    checkpointer = request.app.state.checkpointer
    config = {"configurable": {"thread_id": run_id}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"no checkpoint for run '{run_id}'")
    return dict(checkpoint_tuple.checkpoint["channel_values"])


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, request: Request) -> dict[str, Any]:
    """Resumes a graph run from its last completed checkpoint — kill the pod mid-run,
    resume, and it picks up where it left off. See DEVELOPMENT_PLAN.md's Checkpointing
    chapter for the teaching demo this endpoint is built for."""
    checkpointer = request.app.state.checkpointer
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": run_id}}

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"no checkpoint for run '{run_id}'")

    final_state = await run_graph(graph, None, config)
    return {"decision": final_state.get("decision"), "degraded": final_state.get("degraded", False)}
