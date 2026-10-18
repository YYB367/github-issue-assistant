import json
import math
import threading
from urllib.parse import quote

from filelock import Timeout

from app.config import RETRIEVAL_CONTEXT_BYTES, RETRIEVAL_TOKEN_ESTIMATE_LIMIT, Settings
from app.errors import AppError
from knowledge.embedding import LocalEmbedding
from knowledge.models import Evidence, RetrievalResult
from knowledge.store import VectorStore


class KnowledgeService:
    def __init__(self, settings: Settings, embedder=None, store=None):
        self.settings = settings
        self._embedder = embedder
        self._store = store
        self._load_lock = threading.Lock()

    def ready(self) -> bool:
        return (self.settings.knowledge_path / "active.json").is_file() and (
            self.settings.embedding_model_path / "model-manifest.json").is_file()

    def components(self):
        with self._load_lock:
            if self._embedder is None:
                self._embedder = LocalEmbedding(self.settings)
            if self._store is None:
                self._store = VectorStore(self.settings, self._embedder)
        return self._embedder, self._store

    def search(self, query: str, exclude_issue: int = 0) -> RetrievalResult:
        embedder, store = self.components()
        try:
            with store.lock:
                active = store.active()
                trimmed, vector, truncated = embedder.query(query)
                result = RetrievalResult(status="no_hits", query=trimmed, query_truncated=truncated,
                    top_k=self.settings.retrieval_top_k, max_distance=self.settings.retrieval_max_distance,
                    history_top_k=self.settings.history_top_k, history_max_distance=self.settings.history_max_distance,
                    generation=active["generation"])
                candidates = []
                for kind, k, cutoff in (("document", result.top_k, result.max_distance),
                                         ("historical_issue", result.history_top_k, result.history_max_distance)):
                    for chunk, distance in store.nearest(vector, kind, k, active["generation"], exclude_issue):
                        if not math.isfinite(distance):
                            raise AppError("knowledge_invalid_distance", "检索距离不合法。")
                        distance = min(2.0, max(0.0, distance))
                        if distance > cutoff:
                            result.rejected_by_threshold += 1
                        else:
                            candidates.append((chunk, distance, "vector", []))
                if self.settings.keyword_fallback_enabled and not any(c.source_type == "document" for c, *_ in candidates):
                    fallback = store.keyword_fallback(trimmed, result.top_k, active["generation"])
                    if fallback:
                        result.keyword_fallback_used = True
                        candidates = [(c, None, "keyword", terms) for c, terms in fallback] + candidates
                counter = {"document": 0, "historical_issue": 0}
                for chunk, distance, method, terms in candidates:
                    kind = chunk.source_type
                    next_count = counter[kind] + 1
                    cite_id = ("D" if kind == "document" else "H") + str(next_count)
                    if kind == "document":
                        url = (f"https://github.com/{chunk.repository}/blob/{quote(chunk.version, safe='')}/"
                               f"{quote(chunk.file_path, safe='/')}#L{chunk.line_start}-L{chunk.line_end}")
                    else:
                        url = f"https://github.com/{chunk.repository}/issues/{chunk.issue_number}"
                    evidence = Evidence(**chunk.model_dump(), cite_id=cite_id, distance=distance, url=url,
                        retrieval_method=method, matched_keywords=terms,
                        generation_token_estimate=embedder.estimate_generation_tokens(chunk.text))
                    proposed = result.evidence + [evidence]
                    serialized = json.dumps([e.model_dump() for e in proposed], ensure_ascii=False)
                    token_estimate = embedder.estimate_generation_tokens(serialized)
                    if len(serialized.encode()) > RETRIEVAL_CONTEXT_BYTES or token_estimate > RETRIEVAL_TOKEN_ESTIMATE_LIMIT:
                        result.omitted_by_budget += 1
                        continue
                    counter[kind] = next_count
                    result.evidence.append(evidence)
                    result.context_token_estimate = token_estimate
                if result.evidence:
                    result.status = "searched"
                if truncated:
                    result.warnings.append("检索问题过长，已按Embedding实际token预算缩短；可能遗漏后段信息。")
                if result.omitted_by_budget:
                    result.warnings.append("部分候选片段因检索上下文预算被整体省略，没有截断代码块。")
                if result.keyword_fallback_used:
                    result.warnings.append("文档向量未过阈值，已使用全部技术关键词字面匹配回退；这些片段没有向量距离评分。")
                result.warnings.append("召回仅表示检索条件达标，不等于片段足以解决问题；需人工核对建议依据。")
                if any(e.source_type == "historical_issue" for e in result.evidence):
                    result.warnings.append("历史Issue是未经验证的用户报告，保留更新时间，不能默认视为正确答案。")
                return result
        except Timeout:
            raise AppError("knowledge_busy", "知识库正在入库或检索，稍后重试。") from None
