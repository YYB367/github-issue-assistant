from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from app.config import Settings
from app.errors import AppError
from app.schemas import CommentArgs, IssueArgs
from mcp_server.github import GitHubReader


def create_server(settings: Settings, reader: GitHubReader) -> FastMCP:
    server = FastMCP("github-issue-assistant-v1", log_level="WARNING")
    hints = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    async def run_tool(name: str, arguments: dict) -> dict:
        try:
            if name == "get_issue":
                return await reader.get_issue(IssueArgs.model_validate(arguments))
            return await reader.list_comments(CommentArgs.model_validate(arguments))
        except ValidationError:
            return {"ok": False, "error": {"code": "invalid_tool_arguments", "message": "工具参数不合法。"}}
        except AppError as error:
            return {"ok": False, "error": {"code": error.code, "message": error.message}}

    @server.tool(annotations=hints)
    async def get_issue(
        repository: str,
        issue_number: Annotated[int, Field(gt=0, le=2147483647)],
    ) -> dict:
        """Read one Issue's title, body, state, labels and URL in the allowed repository. Reject PRs."""
        return await run_tool("get_issue", {"repository": repository, "issue_number": issue_number})

    @server.tool(annotations=hints)
    async def list_issue_comments(
        repository: str,
        issue_number: Annotated[int, Field(gt=0, le=2147483647)],
        page: Annotated[int, Field(ge=1, le=2)] = 1,
    ) -> dict:
        """Read 10 comments per page; pages 1 and 2 only, at most 20 comments. Return next_page and limits."""
        return await run_tool("list_issue_comments", {
            "repository": repository, "issue_number": issue_number, "page": page,
        })

    return server


def main() -> None:
    # Only the explicitly injected environment is used; do not load the application's .env.
    settings = Settings(_env_file=None)
    client = httpx.AsyncClient(trust_env=True)
    create_server(settings, GitHubReader(settings, client)).run(transport="stdio")


if __name__ == "__main__":
    main()
