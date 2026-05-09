"""The FastAPI app boots and answers /health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from diary_rag.app import create_app
from diary_rag.config import Settings


def test_health_endpoint_returns_ok() -> None:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "local"
    assert "version" in body
