from fastapi.testclient import TestClient

from app.main import create_app
from conftest import FakeAI


def test_root_supports_get_and_head(settings):
    client = TestClient(create_app(settings))
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "styles.css?v=" in response.text
    assert client.head("/").status_code == 200


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
    assert "strongest collaboration match" in query.json()["answer"]
    assert "Deterministic answer" in query.json()["caveats"][0]

    dataset_query = client.post("/api/query", json={"question": "Which studies use the FieldLeaf-2026 dataset?"})
    assert dataset_query.status_code == 200
    assert "shared by" in dataset_query.json()["answer"]
    assert "FieldLeaf-2026" in dataset_query.json()["answer"]

    overlap_query = client.post("/api/query", json={"question": "Which projects show potential research overlap, and why?"})
    assert overlap_query.status_code == 200
    assert "strongest review signal" in overlap_query.json()["answer"]
    assert "not plagiarism or misconduct" in overlap_query.json()["answer"]


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
