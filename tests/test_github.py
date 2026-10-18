import copy

import httpx
import pytest

from app.config import COMMENT_BODY_CHARS, GITHUB_RESPONSE_BYTES, ISSUE_BODY_CHARS
from app.errors import AppError
from app.schemas import CommentArgs, IssueArgs
from mcp_server.github import GitHubReader
from tests.fixture_mcp import ISSUE, fixture_response
from tests.helpers import REPO, config

ARGS = IssueArgs(repository=REPO, issue_number=1)


@pytest.mark.parametrize("status,code", [(404, "github_not_found"), (401, "github_access_restricted"),
    (403, "github_access_restricted"), (429, "github_access_restricted"), (451, "github_access_restricted"),
    (500, "github_unavailable"), (302, "github_redirect")])
async def test_status_errors(status, code):
    visited = []
    def response(request):
        visited.append(str(request.url))
        return httpx.Response(status, headers={"Location": "https://evil.test"}, json={"message": "secret-canary"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(AppError) as caught:
            await GitHubReader(config(), http).get_issue(ARGS)
    assert caught.value.code == code
    assert "secret-canary" not in caught.value.message
    assert len(visited) == 1


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout("secret"), "github_timeout"),
    (httpx.ConnectError("secret"), "github_connection_error")])
async def test_network_errors(exception, code):
    def response(request):
        raise exception
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(AppError) as caught:
            await GitHubReader(config(), http).get_issue(ARGS)
    assert caught.value.code == code


async def test_server_enforces_repository_before_network():
    def response(request):
        pytest.fail("No request should execute")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(AppError, match="repository_not_allowed"):
            await GitHubReader(config(), http).get_issue(IssueArgs(repository="other/repo", issue_number=1))


@pytest.mark.parametrize("data,code", [({"private": True}, "repository_not_public"),
    ({"private": "false"}, "repository_not_public"), ([], "repository_not_public")])
async def test_public_repository_only(data, code):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as http:
        with pytest.raises(AppError, match=code):
            await GitHubReader(config(), http).get_issue(ARGS)


async def test_pr_disguised_as_issue():
    def response(request):
        if request.url.path.endswith("/issues/1"):
            return httpx.Response(200, json={**ISSUE, "pull_request": {}})
        return fixture_response(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(AppError, match="pull_request"):
            await GitHubReader(config(), http).list_comments(CommentArgs(repository=REPO, issue_number=1))


@pytest.mark.parametrize("content", [b"not-json", b"\xff", b"x" * (GITHUB_RESPONSE_BYTES + 1)],
                         ids=["not-json", "invalid-utf8", "oversized"])
async def test_bad_and_oversized_http_data(content):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as http:
        with pytest.raises(AppError):
            await GitHubReader(config(), http).get_issue(ARGS)


async def test_clip_and_comment_pagination():
    def response(request):
        if request.url.path.endswith("/issues/1"):
            return httpx.Response(200, json={**ISSUE, "body": "x" * (ISSUE_BODY_CHARS + 20), "comments": 25})
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[{"id": i + 1, "body": "x" * (COMMENT_BODY_CHARS + 10),
                "user": {"login": "test"}, "updated_at": "2026-10-12"} for i in range(10)])
        return fixture_response(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        reader = GitHubReader(config(), http)
        issue = await reader.get_issue(ARGS)
        page1 = await reader.list_comments(CommentArgs(repository=REPO, issue_number=1, page=1))
        page2 = await reader.list_comments(CommentArgs(repository=REPO, issue_number=1, page=2))
    assert issue["body_truncated"] and len(issue["body"]) == ISSUE_BODY_CHARS
    assert page1["next_page"] == 2
    assert page2["next_page"] is None and page2["limit_reached"]
    assert len(page2["comments"]) == 10
    assert all(len(c["body"]) == COMMENT_BODY_CHARS and c["body_truncated"] for c in page2["comments"])


async def test_invalid_issue_fields():
    def response(request):
        if request.url.path.endswith("/issues/1"):
            return httpx.Response(200, json={**ISSUE, "number": "1"})
        return fixture_response(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(AppError, match="github_invalid_response"):
            await GitHubReader(config(), http).get_issue(ARGS)
