from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator

from app.base import StrictModel


class SourcesConfig(StrictModel):
    repository: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    paths: list[str] = Field(min_length=1, max_length=10)
    unavailable_document_types: list[str] = Field(default_factory=list)

    @field_validator("paths")
    @classmethod
    def safe_paths(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate source paths")
        for value in values:
            path = PurePosixPath(value)
            if (path.is_absolute() or any(c in value for c in ("\\", ":", "?", "#", "%"))
                    or any(p in ("", ".", "..") for p in value.split("/"))
                    or path.suffix.lower() != ".md" or len(value) > 200):
                raise ValueError("Only repository-relative Markdown paths are allowed")
        return values


class SourceDocument(StrictModel):
    repository: str
    file_path: str
    version: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str
    source_type: Literal["document", "historical_issue"] = "document"
    updated_at: str = ""
    issue_number: int = 0
    title: str = ""


class Chunk(StrictModel):
    chunk_id: str
    repository: str
    file_path: str
    version: str
    content_hash: str
    source_type: Literal["document", "historical_issue"]
    title: str
    line_start: int
    line_end: int
    chunk_index: int
    text: str
    embedding_tokens: int
    updated_at: str = ""
    issue_number: int = 0


class Evidence(Chunk):
    cite_id: str
    distance: float | None
    retrieval_method: Literal["vector", "keyword"] = "vector"
    matched_keywords: list[str] = Field(default_factory=list)
    url: str
    generation_token_estimate: int
    verified_solution: Literal[False] = False


class RetrievalResult(StrictModel):
    status: Literal["searched", "no_hits", "disabled"] = "disabled"
    query: str = ""
    query_truncated: bool = False
    metric: Literal["cosine_distance"] = "cosine_distance"
    top_k: int = 3
    max_distance: float = 0.40
    history_top_k: int = 2
    history_max_distance: float = 0.30
    generation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    rejected_by_threshold: int = 0
    omitted_by_budget: int = 0
    context_token_estimate: int = 0
    warnings: list[str] = Field(default_factory=list)
    keyword_fallback_used: bool = False
