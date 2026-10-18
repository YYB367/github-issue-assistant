import copy
import json
from contextlib import asynccontextmanager

from app.config import Settings
from scripts.demo import DEMO_ANALYSIS

REPO = "YYB367/learning-mcp-server"
URL = f"https://github.com/{REPO}/issues/1"


def config(**kwargs):
    values = dict(allowed_repository=REPO, deepseek_api_key="", github_token="", knowledge_enabled=False, auto_backup_enabled=False)
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def call(name, arguments=None, call_id="call-1", raw=None):
    return {"role": "assistant", "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": name, "arguments": raw if raw is not None else json.dumps(arguments or {"repository": REPO, "issue_number": 1}),
        },
    }]}


def complete():
    return {"role": "assistant", "content": json.dumps(DEMO_ANALYSIS, ensure_ascii=False)}


def normal_sequence():
    return [call("get_issue"), call("list_issue_comments", {"repository": REPO, "issue_number": 1, "page": 1}, "call-2"),
            {"role": "assistant", "content": "Done"}, complete()]


class SequenceModel:
    def __init__(self, sequence):
        self.sequence = sequence
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy((messages, tools)))
        response = self.sequence[len(self.requests) - 1]
        if isinstance(response, Exception):
            raise response
        return response, {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


class StubTools:
    def __init__(self, error=None, body="report"):
        self.calls = []
        self.error = error
        self.body = body
        self.closed = False

    async def definitions(self):
        return [{"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
                for name in ("get_issue", "list_issue_comments")]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return {"ok": True, "repository": REPO, "issue_number": arguments["issue_number"],
                "body": self.body, "comments": [] if name == "list_issue_comments" else None, "next_page": None}

    @asynccontextmanager
    async def connect(self):
        try:
            yield self
        finally:
            self.closed = True
