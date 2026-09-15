"""P10 'done when': SSE stream shows node and token events; resume works."""

import json

import pytest
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

from app.core.settings import Settings
from app.main import create_app
from app.ocr.fixture_provider import FixtureOCRProvider

from ..conftest import (
    FakeAdjudicatorLLM,
    FakeAuditLLM,
    FakeCopyIntakeLLM,
    FakeEmbeddingsClient,
    FakeRepairLLM,
)

FIXTURE_DIR = "tests/fixtures/textract"


@pytest.fixture(autouse=True)
def _reset_sse_appstatus():
    """sse-starlette caches its exit-signal Event on the first event loop that touches it;
    each TestClient spins a fresh loop, so it must be reset between tests or later tests
    fail with 'Event object is bound to a different event loop'."""
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None


def _build_app(tmp_path, graph_store, vector_store):
    settings = Settings(
        vector_backend="numpy",
        documents_dir=str(tmp_path / "documents"),
        sqlite_path=str(tmp_path / "checkpoints.sqlite"),
        fixture_dir=FIXTURE_DIR,
    )
    return create_app(
        settings=settings,
        graph_store=graph_store,
        vector_store=vector_store,
        ocr_provider=FixtureOCRProvider(FIXTURE_DIR),
        intake_llm=FakeCopyIntakeLLM(),
        repair_llm=FakeRepairLLM(),
        adjudicator_llm=FakeAdjudicatorLLM(),
        auditor_llm=FakeAuditLLM(),
        embeddings_client=FakeEmbeddingsClient(),
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    event_name = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
            events.append((event_name, data))
    return events


def test_adjudicate_stream_shows_node_and_token_events(tmp_path, graph_store, vector_store) -> None:
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client, open("tests/fixtures/claims/CLM-001.pdf", "rb") as f:
        response = client.post(
            "/v1/claims/adjudicate",
            files={"file": ("CLM-001.pdf", f, "application/pdf")},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert "node_start" in names
    assert "node_end" in names
    assert "token" in names
    assert "final" in names

    node_start_agents = {data["agent"] for name, data in events if name == "node_start"}
    assert {"intake", "validate", "adjudicate", "audit"} <= node_start_agents

    final_events = [data for name, data in events if name == "final"]
    assert final_events[0]["decision"]["status"] == "APPROVE"


def test_adjudicate_accepts_json_path_body(tmp_path, graph_store, vector_store) -> None:
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client:
        response = client.post(
            "/v1/claims/adjudicate",
            json={"path": "tests/fixtures/claims/CLM-003.pdf"},
        )
    events = _parse_sse(response.text)
    final_events = [data for name, data in events if name == "final"]
    assert final_events[0]["decision"]["status"] == "DENY"


def test_get_run_returns_the_audited_decision(tmp_path, graph_store, vector_store) -> None:
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client:
        stream_response = client.post(
            "/v1/claims/adjudicate", json={"path": "tests/fixtures/claims/CLM-002.pdf"}
        )
        events = _parse_sse(stream_response.text)
        run_id = next(data for name, data in events if name == "final")["run_id"]

        run_response = client.get(f"/v1/runs/{run_id}")
        assert run_response.status_code == 200
        record = run_response.json()
        assert record["run_id"] == run_id
        assert record["status"] == "PARTIAL"
        assert record["decision_json"]["payable_amount"] == 1500

        missing_response = client.get("/v1/runs/does-not-exist")
        assert missing_response.status_code == 404


def test_get_run_state_returns_the_checkpointed_state(tmp_path, graph_store, vector_store) -> None:
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client:
        stream_response = client.post(
            "/v1/claims/adjudicate", json={"path": "tests/fixtures/claims/CLM-001.pdf"}
        )
        events = _parse_sse(stream_response.text)
        run_id = next(data for name, data in events if name == "final")["run_id"]

        state_response = client.get(f"/v1/runs/{run_id}/state")
        assert state_response.status_code == 200
        state = state_response.json()
        assert state["extracted_fields"]["member_id"] == "MEM1001"
        assert state["decision"]["status"] == "APPROVE"


def test_resume_continues_from_the_last_checkpoint(tmp_path, graph_store, vector_store) -> None:
    """Kill the pod mid-run, resume, and it picks up at the last completed node — here
    simulated by resuming a run that already reached END, which should just replay the
    same final decision without error."""
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client:
        stream_response = client.post(
            "/v1/claims/adjudicate", json={"path": "tests/fixtures/claims/CLM-001.pdf"}
        )
        events = _parse_sse(stream_response.text)
        run_id = next(data for name, data in events if name == "final")["run_id"]

        resume_response = client.post(f"/v1/runs/{run_id}/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["decision"]["status"] == "APPROVE"

        missing_response = client.post("/v1/runs/does-not-exist/resume")
        assert missing_response.status_code == 404


def test_get_subgraph_returns_triples_with_clause_ids(tmp_path, graph_store, vector_store) -> None:
    app = _build_app(tmp_path, graph_store, vector_store)
    with TestClient(app) as client:
        response = client.get("/v1/graph/subgraph", params={"codes": "CPT-99213", "hops": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["seed_codes"] == ["CPT-99213"]
    assert any("OP-3.2" in triple for triple in body["triples"])
