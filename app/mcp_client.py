import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import PROJECT_ROOT, TOOL_RESULT_BYTES, Settings
from app.errors import AppError

TOOL_NAMES = {"get_issue", "list_issue_comments"}


class MCPTools:
    def __init__(self, session: ClientSession):
        self.session = session

    async def definitions(self) -> list[dict]:
        result = await self.session.list_tools()
        if {tool.name for tool in result.tools} != TOOL_NAMES:
            raise AppError("mcp_tool_registry", "MCP 工具清单与 V1 的只读白名单不一致。")
        return [{"type": "function", "function": {
            "name": tool.name, "description": tool.description,
            "parameters": tool.inputSchema,
        }} for tool in result.tools]

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_NAMES:
            raise AppError("unknown_tool", "该工具不在 V1 白名单内。")
        result = await self.session.call_tool(name, arguments=arguments)
        if result.isError:
            raise AppError("mcp_tool_error", "MCP 工具拒绝请求或执行失败。")
        data = result.structuredContent
        if data is None:
            texts = [item.text for item in result.content if item.type == "text"]
            if len(texts) != 1 or len(texts[0].encode("utf-8")) > TOOL_RESULT_BYTES:
                raise AppError("mcp_invalid_result", "MCP 工具返回格式或大小不合法。")
            try:
                data = json.loads(texts[0])
            except json.JSONDecodeError:
                raise AppError("mcp_invalid_result", "MCP 工具未返回 JSON 对象。") from None
        if not isinstance(data, dict):
            raise AppError("mcp_invalid_result", "MCP 工具未返回对象。")
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > TOOL_RESULT_BYTES:
            raise AppError("tool_result_too_large", "MCP 返回超过大小上限。")
        if data.get("ok") is not True:
            error = data.get("error", {})
            # Local server messages are safe envelopes, never raw transport exceptions.
            raise AppError(error.get("code", "mcp_tool_error"), error.get("message", "MCP 执行失败。"))
        return data


@asynccontextmanager
async def connect_tools(settings: Settings, module: str = "mcp_server.server"):
    # No model key is passed to the MCP process. SDK merges only a small OS environment.
    env = {
        "ALLOWED_REPOSITORY": settings.allowed_repository,
        "GITHUB_TOKEN": settings.github_token.get_secret_value(),
        "GITHUB_TIMEOUT_SECONDS": str(settings.github_timeout_seconds),
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
    }
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                "SSL_CERT_FILE", "SSL_CERT_DIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    params = StdioServerParameters(
        command=sys.executable, args=["-m", module], cwd=str(PROJECT_ROOT), env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
            await session.initialize()
            yield MCPTools(session)
