from fastapi.testclient import TestClient

from app.main import create_app
from conftest import FakeAI


def test_health_and_demo_critical_flow(settings):
    client = TestClient(create_app(settings))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ai_configured"] is False
    demo = client.post("/api/demo/load")
    assert demo.status_code == 200
    assert demo.json()["synthetic"] is True
    graph = client.get("/api/graph").json()
    assert len(graph["documents"]) == 4
    assert graph["nodes"] and graph["edges"] and graph["insights"]
    query = client.post("/api/query", json={"question": "Who can collaborate on crop disease?"})
    assert query.status_code == 200
    assert "local fallback" in query.json()["caveats"][0]


def test_live_ingestion_requires_server_key(settings):
    client = TestClient(create_app(settings))
    response = client.post("/api/ingest", files={"files": ("paper.md", b"# Paper", "text/markdown")})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_aggregate_request_limit_applies_before_ingestion(settings):
    strict = settings.model_copy(update={"max_request_bytes": 32})
    client = TestClient(create_app(strict))
    response = client.post("/api/ingest", files={"files": ("paper.md", b"#" * 100, "text/markdown")})
    assert response.status_code == 413


def test_successful_provider_ingestion_through_api(settings, sample_text, sample_graph, monkeypatch):
    configured = settings.model_copy(update={"gemini_api_key": "test-only-key"})
    monkeypatch.setattr("app.main.GeminiProvider", lambda *args: FakeAI(sample_graph))
    client = TestClient(create_app(configured))
    response = client.post("/api/ingest", files={"files": ("study.md", sample_text.encode(), "text/markdown")})
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "ingested"
    assert response.json()["stats"]["documents"] == 1
