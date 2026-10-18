import base64
import hashlib

import httpx
import pytest

from app.errors import AppError
from knowledge.ingestion import fetch_documents, fetch_history
from knowledge.models import SourcesConfig
from tests.helpers import REPO, config


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("knowledge.ingestion.httpx.AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), trust_env=False))


async def test_fixed_commit_and_no_arbitrary_download_url(monkeypatch):
    visited = []
    raw = "# 安装\n\n运行npm.cmd install。".encode()
    sha = "b" * 40
    def handler(request):
        visited.append(request)
        assert request.url.host == "api.github.com"
        if request.url.path.endswith("/contents/README.md"):
            assert request.url.params["ref"] == sha
            return httpx.Response(200, json={"type": "file", "encoding": "base64",
                "content": base64.b64encode(raw).decode(), "download_url": "https://evil.test/secret"})
        return httpx.Response(200, json={"private": False})
    mock_client(monkeypatch, handler)
    documents = await fetch_documents(config(), SourcesConfig(repository=REPO, commit=sha, paths=["README.md"]))
    assert documents[0].version == sha and documents[0].content_hash == hashlib.sha256(raw).hexdigest()
    assert len(visited) == 2


async def test_history_limited_and_prs_not_indexed(monkeypatch):
    pages = []
    def handler(request):
        if request.url.path.endswith("/issues"):
            page = int(request.url.params["page"])
            pages.append(page)
            data = [{"number": page * 100 + n, "title": "安装报告", "body": "未验证", "updated_at": "2026-10-14T00:00:00Z"}
                    for n in range(15)]
            data[0]["pull_request"] = {}
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"private": False})
    mock_client(monkeypatch, handler)
    sources = await fetch_history(config(), 30)
    assert pages == [1, 2] and len(sources) == 28
    assert all(s.updated_at and s.source_type == "historical_issue" for s in sources)
    assert all(s.issue_number not in (100, 200) for s in sources)
    assert all("未经验证" in s.text for s in sources)


async def test_invalid_history_limit_rejected_before_network():
    with pytest.raises(AppError, match="history_limit"):
        await fetch_history(config(), 31)


async def test_wrong_repository_rejected_before_network():
    with pytest.raises(AppError, match="knowledge_repository_mismatch"):
        await fetch_documents(config(), SourcesConfig(repository="other/repo", commit="b" * 40, paths=["README.md"]))
