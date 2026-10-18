"""Offline protocol demonstration. Scripted model output is always marked as simulated."""
import argparse
import asyncio
import json

from app.config import Settings
from app.engine import AnalysisRunner
from app.mcp_client import connect_tools

DEMO_ANALYSIS = {
    "summary": "用户报告 npm install 的 ERESOLVE 错误，尚缺少具体依赖冲突和版本信息。",
    "category": "dependency",
    "known_information": ["Issue 报告安装失败；评论仅是未经验证的用户陈述。"],
    "missing_information": ["Node.js 和 npm 版本", "完整报错、安装命令以及复现步骤"],
    "reply_draft": "感谢反馈。请补充 Node.js/npm 版本、执行的安装命令和完整报错。当前未核对项目文档，也未复现，暂时无法确认解决方案。请勿在评论中提供密钥。",
}


class ScriptedDemoModel:
    """Predictable test double; not a substitute for model behavior evaluation."""

    def __init__(self, repository: str, number: int = 1):
        self.repository = repository
        self.number = number
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if tools is None:
            return {"role": "assistant", "content": json.dumps(DEMO_ANALYSIS, ensure_ascii=False)}, {}
        results = [json.loads(msg["content"]) for msg in messages if msg["role"] == "tool"]
        arguments = {"repository": self.repository, "issue_number": self.number}
        if not results:
            name = "get_issue"
        elif not any("comments" in item for item in results):
            name = "list_issue_comments"
            arguments["page"] = 1
        elif results[-1].get("next_page"):
            name = "list_issue_comments"
            arguments["page"] = results[-1]["next_page"]
        else:
            return {"role": "assistant", "content": "已完成读取。"}, {}
        return {"role": "assistant", "tool_calls": [{
            "id": f"demo-{self.calls}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]}, {}


async def run_demo():
    settings = Settings(_env_file=None, deepseek_api_key="", github_token="", knowledge_enabled=False)
    model = ScriptedDemoModel(settings.allowed_repository)
    runner = AnalysisRunner(settings, model=model,
                            connector=lambda: connect_tools(settings, "tests.fixture_mcp"))
    result = await runner.run(f"https://github.com/{settings.allowed_repository}/issues/1")
    result.mode = "offline_demo"
    result.warnings.insert(0, "这是离线演示：GitHub 数据和模型输出均为模拟；MCP stdio 通信和应用循环是真实执行。")
    return result


def main():
    parser = argparse.ArgumentParser(description="不消耗密钥的真实 MCP 离线演示")
    parser.parse_args()
    result = asyncio.run(run_demo())
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "completed" else 1)


if __name__ == "__main__":
    main()
