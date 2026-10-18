"""Admin-only offline ingestion: python -m scripts.kb prepare-model/sync-docs/sync-history/status/search."""
import argparse
import asyncio
import json

from app.config import Settings
from app.errors import find_app_error
from knowledge.embedding import LocalEmbedding, prepare_model
from knowledge.ingestion import fetch_documents, fetch_history, load_snapshot, load_sources, save_snapshot
from knowledge.retrieval import KnowledgeService
from knowledge.store import VectorStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare-model")
    sub.add_parser("sync-docs")
    history = sub.add_parser("sync-history")
    history.add_argument("--limit", type=int, default=20)
    sub.add_parser("status")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--exclude-issue", type=int, default=0)
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.command == "prepare-model":
            output = prepare_model(settings)
        elif args.command == "search":
            output = KnowledgeService(settings).search(args.query, args.exclude_issue).model_dump()
        else:
            embedder = LocalEmbedding(settings)
            store = VectorStore(settings, embedder)
            if args.command == "status":
                output = store.active()
            elif args.command == "sync-docs":
                config = load_sources(settings)
                documents = asyncio.run(fetch_documents(settings, config))
                # Keep bounded historical sources while replacing the entire selected doc manifest.
                if (settings.knowledge_path / "corpus.json").is_file():
                    previous, _ = load_snapshot(settings)
                    documents += [s for s in previous if s.source_type == "historical_issue"]
                output = store.synchronize(documents)
                save_snapshot(settings, documents, config)
                output["unavailable_document_types"] = config.unavailable_document_types
            else:
                documents, config = load_snapshot(settings)
                documents = [s for s in documents if s.source_type == "document"]
                history_documents = asyncio.run(fetch_history(settings, args.limit))
                documents += history_documents
                output = store.synchronize(documents)
                save_snapshot(settings, documents, config)
                output["history_indexed"] = len(history_documents)
                output["requested_limit"] = args.limit
                output["history_verified_solution"] = False
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as error:
        safe = find_app_error(error)
        print(json.dumps({"error": safe.code if safe else "knowledge_command_failed",
                          "message": safe.message if safe else "入库命令失败，请核对模型、配置与本地目录。",
                          "exception_type": type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
