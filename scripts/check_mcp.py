"""Read-only live MCP connectivity check. No model calls and no GitHub writes."""
import argparse
import asyncio
import json

from app.config import Settings
from app.errors import find_app_error
from app.mcp_client import connect_tools
from app.schemas import parse_issue_url


async def check(url):
    settings = Settings()
    target = parse_issue_url(url, settings.allowed_repository)
    try:
        async with asyncio.timeout(settings.task_timeout_seconds):
            async with connect_tools(settings) as tools:
                definitions = await tools.definitions()
                print(json.dumps({"discovered_tools": [t["function"]["name"] for t in definitions]}))
                issue = await tools.call("get_issue", target.model_dump())
                comments = await tools.call("list_issue_comments", {**target.model_dump(), "page": 1})
                print(json.dumps({"issue": issue, "comments_page_1": comments}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        safe = find_app_error(error)
        print(json.dumps({"error": safe.code if safe else "mcp_check_failed"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_url")
    raise SystemExit(asyncio.run(check(parser.parse_args().issue_url)))
