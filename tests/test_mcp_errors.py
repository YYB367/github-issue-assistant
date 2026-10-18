from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.engine import AnalysisRunner
from app.errors import find_app_error
from tests.helpers import URL, SequenceModel, StubTools, call, config


async def test_mcp_sdk_timeout_is_explicit():
    tools = StubTools(McpError(ErrorData(code=408, message="secret-canary")))
    result = await AnalysisRunner(config(), SequenceModel([call("get_issue")]), tools.connect).run(URL)
    assert result.status == "timed_out" and result.error.code == "mcp_timeout"
    assert result.tool_trace[0].status == "timed_out"
    assert "secret-canary" not in result.model_dump_json()


def test_nested_transport_error_sanitized():
    error = ExceptionGroup("secret", [ExceptionGroup("nested", [McpError(ErrorData(code=-32000, message="secret-canary"))])])
    safe = find_app_error(error)
    assert safe.code == "mcp_transport_error" and "secret-canary" not in safe.message
