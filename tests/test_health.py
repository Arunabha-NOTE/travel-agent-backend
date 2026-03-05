from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_observability_health():
    response = client.get("/api/v1/observability/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["metrics"]["enabled"] is True
    assert payload["metrics"]["endpoint"] == "/metrics"
    assert "tracing" in payload
