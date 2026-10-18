import hashlib
import json
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from filelock import FileLock, Timeout

from app.config import EMBEDDING_TOKEN_LIMIT, Settings
from app.errors import AppError
from knowledge.chunking import CHUNKER_VERSION, split_markdown
from knowledge.models import Chunk, SourceDocument


class VectorStore:
    """Publish a generation only after all upserts succeed; queries filter that generation."""
    def __init__(self, settings: Settings, embedder):
        self.settings = settings
        self.embedder = embedder
        self.folder = settings.knowledge_path
        self.folder.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.folder / "chroma"),
            settings=ChromaSettings(anonymized_telemetry=False))
        signature = hashlib.sha256(embedder.identity.encode()).hexdigest()[:16]
        self.collection = self.client.get_or_create_collection("issue_assistant_" + signature,
            embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_identity": embedder.identity, "metric": "cosine_distance",
                      "repository": settings.allowed_repository})
        if self.collection.configuration["hnsw"]["space"] != "cosine":
            raise AppError("knowledge_metric_mismatch", "Chroma集合距离配置不一致。")
        self.lock = FileLock(str(self.folder / "index.lock"), timeout=1)

    def active(self) -> dict:
        path = self.folder / "active.json"
        if not path.is_file():
            raise AppError("knowledge_not_ready", "请先执行 python -m scripts.kb sync-docs 入库。")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("repository", "").casefold() != self.settings.allowed_repository.casefold()
                or data.get("embedding_identity") != self.embedder.identity
                or data.get("collection") != self.collection.name):
            raise AppError("knowledge_version_mismatch", "知识库与当前仓库或Embedding版本不一致，请重新入库。")
        return data

    def synchronize(self, sources: list[SourceDocument]) -> dict:
        if not sources or len(sources) > 40 or sum(len(s.text.encode()) for s in sources) > 400000:
            raise AppError("knowledge_corpus_limit", "知识源数量、总大小或空库不合法。")
        if any(s.repository.casefold() != self.settings.allowed_repository.casefold() for s in sources):
            raise AppError("knowledge_repository_mismatch", "知识源不在允许范围内。")
        if len({(s.source_type, s.file_path) for s in sources}) != len(sources):
            raise AppError("duplicate_knowledge_source", "知识来源重复。")
        chunks = []
        for source in sorted(sources, key=lambda s: (s.source_type, s.file_path)):
            if hashlib.sha256(source.text.encode()).hexdigest() != source.content_hash:
                raise AppError("knowledge_hash_mismatch", "来源内容与哈希不一致。")
            chunks.extend(split_markdown(source, self.embedder.tokenizer))
        if len(chunks) > 512:
            raise AppError("knowledge_chunk_limit", "知识片段数量超过512条。")
        generation = hashlib.sha256(json.dumps([self.embedder.identity, CHUNKER_VERSION,
            EMBEDDING_TOKEN_LIMIT, [c.chunk_id for c in chunks]]).encode()).hexdigest()
        ids = [generation[:16] + ":" + c.chunk_id for c in chunks]
        try:
            with self.lock.acquire(timeout=30):
                existing = set(self.collection.get(where={"generation": generation}, include=[]) ["ids"])
                added, reused = 0, 0
                for offset in range(0, len(chunks), 8):
                    batch = [(i, c) for i, c in zip(ids[offset:offset + 8], chunks[offset:offset + 8]) if i not in existing]
                    reused += min(8, len(chunks) - offset) - len(batch)
                    if not batch:
                        continue
                    vectors = self.embedder.encode([c.text for _, c in batch])
                    self.collection.upsert(ids=[i for i, _ in batch], embeddings=vectors,
                        documents=[c.text for _, c in batch], metadatas=[{
                            **c.model_dump(exclude={"text"}), "generation": generation,
                        } for _, c in batch])
                    added += len(batch)
                record = {"repository": self.settings.allowed_repository, "generation": generation,
                    "collection": self.collection.name, "embedding_identity": self.embedder.identity,
                    "chunker": CHUNKER_VERSION, "embedding_token_limit": EMBEDDING_TOKEN_LIMIT,
                    "chunk_count": len(chunks), "documents": [{**s.model_dump(exclude={"text"})} for s in sources]}
                temp = self.folder / "active.tmp"
                temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(self.folder / "active.json")
                # Old and abandoned generations are removed ONLY after publishing the complete new one.
                stale = self.collection.get(where={"generation": {"$ne": generation}}, include=[])["ids"]
                if stale:
                    self.collection.delete(ids=stale)
                for collection in self.client.list_collections():
                    if (collection.name.startswith("issue_assistant_") and collection.name != self.collection.name
                            and (collection.metadata or {}).get("repository") == self.settings.allowed_repository):
                        self.client.delete_collection(collection.name)
                return {"generation": generation, "added": added, "reused": reused,
                        "deleted": len(stale), "chunks": len(chunks), "metric": "cosine_distance"}
        except Timeout:
            raise AppError("knowledge_busy", "知识库正在被使用，稍后重试入库。") from None

    def nearest(self, vector, source_type: str, k: int, generation: str, exclude_issue: int = 0) -> list[tuple[Chunk, float]]:
        conditions = [{"repository": self.settings.allowed_repository}, {"generation": generation},
                      {"source_type": source_type}]
        if source_type == "historical_issue" and exclude_issue:
            conditions.append({"issue_number": {"$ne": exclude_issue}})
        found = self.collection.query(query_embeddings=[vector], n_results=k,
            where={"$and": conditions}, include=["documents", "metadatas", "distances"])
        hits = []
        for metadata, text, distance in zip(found["metadatas"][0], found["documents"][0], found["distances"][0]):
            metadata = dict(metadata)
            metadata.pop("generation", None)
            hits.append((Chunk.model_validate({**metadata, "text": text}), float(distance)))
        return hits

    def keyword_fallback(self, query: str, k: int, generation: str) -> list[tuple[Chunk, list[str]]]:
        # Only after vector docs miss. All literal technical terms must match; no mixed similarity scores.
        stopwords = {"where", "what", "how", "should", "this", "that", "the", "and", "for", "with", "can"}
        terms = {t.casefold() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", query)} - stopwords
        terms.update(word for word in ("密钥", "执行策略", "镜像源", "代理", "配置") if word in query)
        if not 2 <= len(terms) <= 5:
            return []
        data = self.collection.get(where={"$and": [{"repository": self.settings.allowed_repository},
            {"generation": generation}, {"source_type": "document"}]}, include=["documents", "metadatas"])
        matches = []
        for metadata, text in zip(data["metadatas"], data["documents"]):
            if all(term in text.casefold() for term in terms):
                metadata = dict(metadata)
                metadata.pop("generation", None)
                matches.append((Chunk.model_validate({**metadata, "text": text}), sorted(terms)))
        # Shorter complete fragments first, then stable source order. This is not a probability or vector rank.
        matches.sort(key=lambda item: (item[0].embedding_tokens, item[0].file_path, item[0].line_start))
        return matches[:k]
