import asyncio
import json

from app.engine import AnalysisRunner
from app.mcp_client import connect_tools
from scripts.demo import ScriptedDemoModel, run_demo
from tests.helpers import REPO, URL, config
from tests.test_engine import SlowModel


async def test_actual_stdio_protocol_and_pagination():
    result = await run_demo()
    assert result.status == "completed" and result.mode == "offline_demo"
    assert [t.arguments.get("page") for t in result.tool_trace] == [None, 1, 2]
    assert all(t.status == "success" for t in result.tool_trace)
    assert result.model_calls == 5


async def test_model_credential_is_not_in_child_environment(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "credential-isolation-canary")
    result = await run_demo()
    assert result.status == "completed"
    assert "credential-isolation-canary" not in result.model_dump_json()


async def test_server_allowlist_and_parameter_schema():
    settings = config()
    async with connect_tools(settings, "tests.fixture_mcp") as tools:
        definitions = await tools.definitions()
        assert len(definitions) == 2
        bad = await tools.session.call_tool("get_issue", {"repository": "other/repo", "issue_number": 1})
        data = bad.structuredContent or json.loads(bad.content[0].text)
        assert data["error"]["code"] == "repository_not_allowed"
        bad = await tools.session.call_tool("list_issue_comments", {"repository": REPO, "issue_number": 1, "page": 3})
        assert bad.isError


async def test_real_mcp_cancellation_after_initialization():
    settings = config()
    model = SlowModel()
    runner = AnalysisRunner(settings, model, lambda: connect_tools(settings, "tests.fixture_mcp"))
    worker = asyncio.create_task(runner.run(URL))
    await asyncio.wait_for(model.entered.wait(), timeout=10)
    worker.cancel()
    result = await asyncio.wait_for(worker, timeout=10)
    assert result.status == "cancelled"


async def test_real_mcp_whole_task_timeout():
    settings = config(task_timeout_seconds=2)
    runner = AnalysisRunner(settings, SlowModel(), lambda: connect_tools(settings, "tests.fixture_mcp"))
    result = await runner.run(URL)
    assert result.status == "timed_out" and result.error.code == "task_timeout"
