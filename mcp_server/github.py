import json
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import (
    COMMENT_BODY_CHARS, COMMENTS_PER_PAGE, GITHUB_RESPONSE_BYTES,
    ISSUE_BODY_CHARS, MAX_COMMENT_PAGES, TOOL_RESULT_BYTES, Settings,
)
from app.errors import AppError
from app.schemas import CommentArgs, IssueArgs


class GitHubIssue(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    number: int
    title: str
    body: str | None
    state: str
    labels: list[dict]
    comments: int = Field(ge=0)
    updated_at: str


class GitHubComment(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: int = Field(gt=0)
    body: str | None
    user: dict
    updated_at: str


def bounded_result(payload: dict) -> dict:
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > TOOL_RESULT_BYTES:
        raise AppError("tool_result_too_large", "工具结果超过大小上限，任务已停止。")
    return payload


class GitHubReader:
    """Only builds two issue endpoints and a public-repository check on api.github.com."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.public_checked = False
        self.issues: dict[int, dict] = {}

    def validate_target(self, args: IssueArgs) -> None:
        if args.repository.casefold() != self.settings.allowed_repository.casefold():
            raise AppError("repository_not_allowed", "该仓库不在配置允许的范围内。")

    def repo_path(self) -> str:
        owner, repo = self.settings.allowed_repository.split("/")
        return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"

    async def request(self, suffix: str, params: dict | None = None) -> object:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-issue-assistant-v1",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        token = self.settings.github_token.get_secret_value()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with self.client.stream(
                "GET", "https://api.github.com" + self.repo_path() + suffix,
                params=params, headers=headers,
                timeout=self.settings.github_timeout_seconds, follow_redirects=False,
            ) as response:
                code = response.status_code
                if code == 404:
                    raise AppError("github_not_found", "GitHub 未找到仓库或 Issue，也可能当前凭证无权访问。")
                if code in (401, 403, 429, 451):
                    raise AppError("github_access_restricted", "GitHub 拒绝访问：可能是凭证、权限、限流或访问限制。")
                if 300 <= code < 400:
                    raise AppError("github_redirect", "GitHub 返回重定向；请核对仓库配置，程序不会跟随其他地址。")
                if code != 200:
                    raise AppError("github_unavailable", "GitHub 接口暂时不可用。")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > GITHUB_RESPONSE_BYTES:
                        raise AppError("github_response_too_large", "GitHub 响应超过读取上限。")
                return json.loads(data)
        except httpx.TimeoutException:
            raise AppError("github_timeout", "读取 GitHub 超时，未取得完整结果。") from None
        except httpx.RequestError:
            raise AppError("github_connection_error", "无法连接 GitHub。") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AppError("github_invalid_response", "GitHub 返回了无法解析的响应。") from None

    async def ensure_public(self) -> None:
        if not self.public_checked:
            repo = await self.request("")
            if not isinstance(repo, dict) or repo.get("private") is not False:
                raise AppError("repository_not_public", "V1 仅允许公开仓库。")
            self.public_checked = True

    async def get_issue(self, args: IssueArgs) -> dict:
        self.validate_target(args)
        await self.ensure_public()
        if args.issue_number in self.issues:
            return self.issues[args.issue_number]
        data = await self.request(f"/issues/{args.issue_number}")
        if not isinstance(data, dict):
            raise AppError("github_invalid_response", "GitHub Issue 响应结构不合法。")
        if "pull_request" in data:
            raise AppError("pull_request", "该编号实际对应 Pull Request，V1 不处理。")
        try:
            issue = GitHubIssue.model_validate(data)
            if issue.number != args.issue_number or issue.state not in ("open", "closed"):
                raise ValueError
        except (ValidationError, ValueError):
            raise AppError("github_invalid_response", "GitHub Issue 字段不合法。") from None
        body = issue.body or ""
        result = bounded_result({
            "ok": True, "repository": self.settings.allowed_repository,
            "issue_number": issue.number, "title": issue.title[:256],
            "body": body[:ISSUE_BODY_CHARS], "body_truncated": len(body) > ISSUE_BODY_CHARS,
            "state": issue.state,
            "labels": [label["name"][:100] for label in issue.labels[:20]
                       if isinstance(label.get("name"), str)],
            "labels_truncated": len(issue.labels) > 20,
            "url": f"https://github.com/{self.settings.allowed_repository}/issues/{issue.number}",
            "comment_count": issue.comments, "updated_at": issue.updated_at[:40],
            "external_data": True,
        })
        self.issues[args.issue_number] = result
        return result

    async def list_comments(self, args: CommentArgs) -> dict:
        self.validate_target(args)
        issue = await self.get_issue(IssueArgs(repository=args.repository, issue_number=args.issue_number))
        data = await self.request(f"/issues/{args.issue_number}/comments", {
            "page": args.page, "per_page": COMMENTS_PER_PAGE,
        })
        if not isinstance(data, list) or len(data) > COMMENTS_PER_PAGE:
            raise AppError("github_invalid_response", "GitHub 评论列表结构不合法。")
        try:
            comments = [GitHubComment.model_validate(item) for item in data]
        except ValidationError:
            raise AppError("github_invalid_response", "GitHub 评论字段不合法。") from None
        result_items = []
        for comment in comments:
            body = comment.body or ""
            login = comment.user.get("login")
            result_items.append({
                "id": comment.id, "author": login[:100] if isinstance(login, str) else "unknown",
                "body": body[:COMMENT_BODY_CHARS], "body_truncated": len(body) > COMMENT_BODY_CHARS,
                "url": issue["url"] + f"#issuecomment-{comment.id}",
                "updated_at": comment.updated_at[:40],
            })
        # Counts are a snapshot; a full page is conservatively treated as possibly having more.
        possible_more = (len(comments) == COMMENTS_PER_PAGE
                         or issue["comment_count"] > args.page * COMMENTS_PER_PAGE)
        return bounded_result({
            "ok": True, "repository": self.settings.allowed_repository,
            "issue_number": args.issue_number, "page": args.page,
            "per_page": COMMENTS_PER_PAGE, "comments": result_items,
            "total_at_issue_read": issue["comment_count"],
            "next_page": args.page + 1 if possible_more and args.page < MAX_COMMENT_PAGES else None,
            "possibly_more": possible_more,
            "limit_reached": possible_more and args.page == MAX_COMMENT_PAGES,
            "external_data": True,
        })
