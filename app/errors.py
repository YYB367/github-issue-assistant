from mcp.shared.exceptions import McpError


class AppError(Exception):
    """Only these safe messages are returned; never upstream exception text."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


def find_app_error(exc: BaseException) -> AppError | None:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, McpError):
        if exc.error.code == 408:
            return AppError("mcp_timeout", "等待 MCP 服务响应超时。")
        return AppError("mcp_transport_error", "MCP 会话请求失败。")
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = find_app_error(child)
            if found:
                return found
    return None
