"""Record vector baseline/fallback and optionally real-model cases with SIMULATED Issue data."""
import argparse
import asyncio
import json
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.engine import AnalysisRunner
from app.mcp_client import connect_tools
from knowledge.retrieval import KnowledgeService

DEVELOPMENT_QUERIES = [
    "项目需要什么Node.js版本？怎样安装？",
    "PowerShell提示npm.ps1无法加载，执行策略阻止npm怎么办？",
    "应该在哪里配置DeepSeek API Key？",
    "DeepSeek密钥应该写到哪个文件？",
    "npm install 报ERESOLVE，具体依赖冲突怎样解决？",
    "太阳系最大的行星是什么？",
]


def retrieval_records(settings):
    baseline = KnowledgeService(settings.model_copy(update={"keyword_fallback_enabled": False}))
    service = KnowledgeService(settings)
    dev = [{"split": "development", "query": q, "vector_only": baseline.search(q, 1).model_dump(),
            "with_fallback": service.search(q, 1).model_dump()} for q in DEVELOPMENT_QUERIES]
    cases = json.loads((PROJECT_ROOT / "knowledge" / "evaluation-cases.json").read_text())["cases"]
    evaluation = []
    for case in cases:
        result = service.search(case["query"], 1)
        text = "\n".join(e.text for e in result.evidence)
        # Mechanical checks of listed facts only. This is NOT an answer accuracy rating.
        evaluation.append({**case, "split": "evaluation", "retrieval": result.model_dump(),
                           "listed_facts_present": all(f in text for f in case["expected_facts"])
                           if case["expected_support"] else None,
                           "manual_relevance_review": "pending"})
    return {"development": dev, "evaluation": evaluation}


async def model_records(settings, numbers):
    service = KnowledgeService(settings)
    records = []
    for number in numbers:
        runner = AnalysisRunner(settings, connector=lambda: connect_tools(settings, "tests.fixture_mcp_v2"), knowledge=service)
        result = await runner.run(f"https://github.com/{settings.allowed_repository}/issues/{number}")
        result.mode = "offline_demo"
        result.warnings.insert(0, "评估使用模拟GitHub Issue数据；MCP通信、Embedding、Chroma和DeepSeek模型请求是真实执行。")
        records.append({"case": number, "split": "evaluation", "issue_data": "simulated",
                        "embedding": "real_local", "model": "live_deepseek", "response": result.model_dump(),
                        "manual_grounding_review": "pending"})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-cases", nargs="*", type=int, choices=[201, 202, 203, 204, 205])
    parser.add_argument("--regression", action="store_true", help="标为开发回归，保留先前独立评估结果")
    parser.add_argument("--holdout", action="store_true", help="新案例单独保存，不覆盖首轮最终评估")
    args = parser.parse_args()
    settings = Settings()
    folder = PROJECT_ROOT / "verification"
    if args.model_cases is not None:
        records = asyncio.run(model_records(settings, args.model_cases or [201, 203, 204]))
        if args.holdout:
            path = folder / "v2-model-holdout.json"
        elif args.regression:
            for row in records:
                row["split"] = "development_regression"
            path = folder / "v2-model-regressions.json"
        else:
            path = folder / "v2-model-evaluation.json"
    else:
        records = retrieval_records(settings)
        path = folder / "v2-retrieval-evaluation.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": path.name, "model_requests_used": args.model_cases is not None,
                      "records": len(records) if isinstance(records, list) else len(records["evaluation"])}))


if __name__ == "__main__":
    main()
