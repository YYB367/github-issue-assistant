import asyncio
import json
import pytest

from fastapi.testclient import TestClient

from app.api import create_app
from app.engine import AnalysisRunner
from app.errors import AppError
from tests.helpers import URL, SequenceModel, StubTools, config, normal_sequence
from tests.test_engine import SlowModel
from tests.test_knowledge import StubKnowledge, source_evidence, knowledge_answer
from knowledge.models import RetrievalResult


@pytest.fixture(autouse=True)
def isolated_state_database(tmp_path, monkeypatch):
    original = config
    monkeypatch.setattr("tests.test_api.config", lambda **kwargs: original(
        state_db_path=tmp_path / "sessions.db", **kwargs))


def test_http_health_schema_and_analysis():
    app = create_app(config(), lambda s: AnalysisRunner(s, SequenceModel(normal_sequence()), StubTools().connect))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200 and health.json()["model_configured"] is False
        assert client.get("/docs").status_code == 200
        assert "AnalyzeResponse" in client.get("/openapi.json").json()["components"]["schemas"]
        result = client.post("/analyze", json={"issue_url": URL})
        assert result.status_code == 200 and result.json()["status"] == "completed"
        assert result.json()["documentation_checked"] is False
        assert client.post("/analyze", json={"issue_url": URL, "publish": True}).status_code == 422
        assert client.post("/analyze", json={"issue_url": 123}).status_code == 422


def test_invalid_target_http_codes():
    app = create_app(config())
    with TestClient(app) as client:
        assert client.post("/analyze", json={"issue_url": "https://evil.test"}).status_code == 400
        assert client.post("/analyze", json={"issue_url": URL.replace("issues", "pull")}).status_code == 400
        assert client.post("/analyze", json={"issue_url": URL.replace("YYB367", "other")}).status_code == 403
        assert client.post("/analyze", json={"issue_url": URL}).status_code == 503


def test_github_error_http_code():
    app = create_app(config(), lambda s: AnalysisRunner(s, SequenceModel(normal_sequence()),
        StubTools(AppError("github_not_found", "未找到")).connect))
    with TestClient(app) as client:
        result = client.post("/analyze", json={"issue_url": URL})
        assert result.status_code == 404 and result.json()["analysis"] is None


async def test_asgi_disconnect_cancels_worker():
    model, tools = SlowModel(), StubTools()
    app = create_app(config(), lambda s: AnalysisRunner(s, model, tools.connect))
    sent, received = [], 0
    async def receive():
        nonlocal received
        received += 1
        if received == 1:
            return {"type": "http.request", "body": json.dumps({"issue_url": URL}).encode(), "more_body": False}
        await model.entered.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
             "method": "POST", "path": "/analyze", "raw_path": b"/analyze", "query_string": b"",
             "headers": [(b"content-type", b"application/json"), (b"host", b"127.0.0.1:8000")], "client": ("127.0.0.1", 1),
             "server": ("127.0.0.1", 8000), "root_path": ""}
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
    assert sent[0]["status"] == 499
    assert json.loads(sent[1]["body"])["status"] == "cancelled" and tools.closed


def test_v2_search_endpoint_and_opt_out(monkeypatch):
    service = StubKnowledge([source_evidence()])
    service.search = lambda query, exclude_issue: RetrievalResult(
        status="searched", query=query, evidence=[source_evidence()])
    monkeypatch.setattr("knowledge.retrieval.KnowledgeService", lambda s: service)
    def runner(s):
        seq = normal_sequence()[:-1] + [knowledge_answer(["D1"]) if s.knowledge_enabled else normal_sequence()[-1]]
        return AnalysisRunner(s, SequenceModel(seq), StubTools().connect, service)
    app = create_app(config(knowledge_enabled=True), runner)
    with TestClient(app) as client:
        assert client.get("/health").json()["knowledge_ready"]
        result = client.post("/knowledge/search", json={"query": "安装"})
        assert result.status_code == 200 and result.json()["evidence"][0]["cite_id"] == "D1"
        result = client.post("/analyze", json={"issue_url": URL})
        assert result.status_code == 200 and result.json()["analysis"]["recommendations"][0]["evidence_ids"] == ["D1"]
        assert result.json()["documentation_checked"]
        result = client.post("/analyze", json={"issue_url": URL, "use_knowledge": False})
        assert result.status_code == 200 and result.json()["retrieval"] is None
        assert "recommendations" not in result.json()["analysis"]
        assert client.get("/health").json()["knowledge_enabled"]


def test_knowledge_not_ready_returns_503(tmp_path):
    app = create_app(config(knowledge_enabled=True, knowledge_path=tmp_path))
    with TestClient(app) as client:
        result = client.post("/knowledge/search", json={"query": "安装"})
        assert result.status_code == 503
        result = client.post("/analyze", json={"issue_url": URL})
        assert result.status_code == 503 and result.json()["error"]["code"] == "knowledge_not_ready"
