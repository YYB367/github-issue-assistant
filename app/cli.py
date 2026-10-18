import argparse
import asyncio
import logging

from app.config import Settings
from app.engine import AnalysisRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="真实模型 + 真实 GitHub + stdio MCP 分析")
    parser.add_argument("issue_url")
    parser.add_argument("--without-knowledge", action="store_true", help="明确使用V1的无知识库流程")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    settings = Settings()
    if args.without_knowledge:
        settings = settings.model_copy(update={"knowledge_enabled": False})
    result = asyncio.run(AnalysisRunner(settings).run(args.issue_url))
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "completed" else 1)


if __name__ == "__main__":
    main()
