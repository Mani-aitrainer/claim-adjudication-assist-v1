from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app


def _test_app(tmp_path):
    settings = Settings(
        vector_backend="numpy",
        documents_dir=str(tmp_path / "documents"),
        sqlite_path=str(tmp_path / "checkpoints.sqlite"),
    )
    return create_app(settings=settings)


def test_healthz_returns_ok(tmp_path) -> None:
    with TestClient(_test_app(tmp_path)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_a_status_and_checks(tmp_path) -> None:
    with TestClient(_test_app(tmp_path)) as client:
        response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "checks" in body
    assert set(body["checks"]) == {"vector_store", "cache", "secret"}
    assert body["checks"]["vector_store"] == "ok"
    assert body["checks"]["cache"] == "ok"
