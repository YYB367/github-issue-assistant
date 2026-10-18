import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import PROJECT_ROOT, Settings
from app.errors import AppError
from knowledge.models import SourceDocument, SourcesConfig
from mcp_server.github import GitHubReader

SOURCES_PATH = PROJECT_ROOT / "knowledge" / "sources.json"


def load_sources(settings: Settings, path: Path = SOURCES_PATH) -> SourcesConfig:
    config = SourcesConfig.model_validate_json(path.read_text(encoding="utf-8-sig"))
    if config.repository.casefold() != settings.allowed_repository.casefold():
        raise AppError("knowledge_repository_mismatch", "知识源仓库与允许仓库不一致。")
    return config


async def fetch_documents(settings: Settings, config: SourcesConfig) -> list[SourceDocument]:
    if config.repository.casefold() != settings.allowed_repository.casefold():
        raise AppError("knowledge_repository_mismatch", "知识源不在允许仓库范围内。")
    documents = []
    async with httpx.AsyncClient(trust_env=True) as client:
        reader = GitHubReader(settings, client)
        await reader.ensure_public()
        for path in config.paths:
            data = await reader.request("/contents/" + quote(path, safe="/"), {"ref": config.commit})
            if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
                raise AppError("knowledge_source_invalid", "文档源不是可读取的Markdown文件。")
            try:
                raw = base64.b64decode(data["content"].replace("\n", ""), validate=True)
                if len(raw) > 128000:
                    raise ValueError
                text = raw.decode("utf-8")
            except (KeyError, ValueError, UnicodeDecodeError):
                raise AppError("knowledge_source_invalid", "文档编码或大小不合法。") from None
            documents.append(SourceDocument(repository=settings.allowed_repository, file_path=path,
                version=config.commit, content_hash=hashlib.sha256(raw).hexdigest(), text=text))
    return documents


async def fetch_history(settings: Settings, limit: int = 20) -> list[SourceDocument]:
    if not 1 <= limit <= 30:
        raise AppError("history_limit", "历史Issue索引最多30条。")
    sources = []
    async with httpx.AsyncClient(trust_env=True) as client:
        reader = GitHubReader(settings, client)
        await reader.ensure_public()
        # Two pages of 15 raw entries; PR filtering can yield fewer than requested.
        for page in (1, 2):
            entries = await reader.request("/issues", {"state": "all", "sort": "updated",
                "direction": "desc", "per_page": 15, "page": page})
            if not isinstance(entries, list):
                raise AppError("github_invalid_response", "历史Issue列表结构不合法。")
            for entry in entries:
                if not isinstance(entry, dict) or "pull_request" in entry:
                    continue
                number, title, body, updated = (entry.get(k) for k in ("number", "title", "body", "updated_at"))
                if (type(number) is not int or number <= 0 or not isinstance(title, str)
                        or not isinstance(body, (str, type(None))) or not isinstance(updated, str)):
                    raise AppError("github_invalid_response", "历史Issue字段不合法。")
                if len(body or "") > 6000:
                    # Skip explicitly rather than treating a clipped old reply as authoritative.
                    continue
                text = f"# {title}\n\n历史用户报告，未经验证，不代表解决方案。\n\n{body or ''}"
                sources.append(SourceDocument(repository=settings.allowed_repository,
                    file_path=f"issues/{number}", version=updated, updated_at=updated,
                    content_hash=hashlib.sha256(text.encode()).hexdigest(), text=text,
                    source_type="historical_issue", issue_number=number, title=title))
                if len(sources) >= limit:
                    return sources
            if len(entries) < 15:
                break
    return sources


def save_snapshot(settings: Settings, documents: list[SourceDocument], config: SourcesConfig) -> Path:
    destination = settings.knowledge_path / "corpus.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(),
               "sources": config.model_dump(), "documents": [d.model_dump() for d in documents]}
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(destination)
    return destination


def load_snapshot(settings: Settings) -> tuple[list[SourceDocument], SourcesConfig]:
    path = settings.knowledge_path / "corpus.json"
    if not path.is_file():
        raise AppError("knowledge_not_ready", "请先执行 python -m scripts.kb sync-docs。")
    data = json.loads(path.read_text(encoding="utf-8"))
    config = SourcesConfig.model_validate(data["sources"])
    documents = [SourceDocument.model_validate(d) for d in data["documents"]]
    return documents, config
