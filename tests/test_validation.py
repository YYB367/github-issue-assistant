import pytest
from pydantic import ValidationError

from app.errors import AppError
from app.schemas import CommentArgs, parse_issue_url
from tests.helpers import REPO, URL


@pytest.mark.parametrize("value,code", [
    ("http://github.com/YYB367/learning-mcp-server/issues/1", "invalid_issue_url"),
    ("https://github.com.evil.test/YYB367/learning-mcp-server/issues/1", "invalid_issue_url"),
    ("https://github.com@evil.test/YYB367/learning-mcp-server/issues/1", "invalid_issue_url"),
    ("https://github.com:443/YYB367/learning-mcp-server/issues/1", "invalid_issue_url"),
    (URL + "?redirect=https://evil.test", "invalid_issue_url"),
    (URL.replace("issues/1", "pull/1"), "pull_request"),
    (URL.replace(REPO, "other/repo"), "repository_not_allowed"),
    (URL.replace("issues/1", "issues/0"), "invalid_issue_url"),
    (URL.replace("issues/1", "issues/2147483648"), "invalid_issue_url"),
    (URL.replace("issues/1", "issues/%31"), "invalid_issue_url"),
])
def test_url_rejections(value, code):
    with pytest.raises(AppError) as caught:
        parse_issue_url(value, REPO)
    assert caught.value.code == code


def test_canonical_target():
    target = parse_issue_url(URL.lower() + "/#issuecomment-2", REPO)
    assert target.repository == REPO
    assert target.url == URL


@pytest.mark.parametrize("extra", [{"page": 3}, {"page": 0}, {"page": "1"}, {"issue_number": True}, {"url": "https://evil.test"}])
def test_strict_tool_arguments(extra):
    with pytest.raises(ValidationError):
        CommentArgs.model_validate({"repository": REPO, "issue_number": 1, **extra})
