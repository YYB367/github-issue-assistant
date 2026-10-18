import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field
from app.base import StrictModel

from app.errors import AppError


class IssueTarget(StrictModel):
    repository: str
    issue_number: int = Field(gt=0, le=2147483647)

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repository}/issues/{self.issue_number}"


def parse_issue_url(value: str, allowed_repository: str) -> IssueTarget:
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.netloc.lower() != "github.com"
                or parts.query or parts.username or parts.password):
            raise ValueError
        match = re.fullmatch(
            r"/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+)/(issues|pull)/([1-9][0-9]{0,9})/?",
            parts.path,
        )
        if not match:
            raise ValueError
        owner, repo, kind, number = match.groups()
        if kind == "pull":
            raise AppError("pull_request", "请提交 Issue 链接，V1 不处理 Pull Request。")
        repository = f"{owner}/{repo}"
        if repository.casefold() != allowed_repository.casefold():
            raise AppError("repository_not_allowed", "该仓库不在配置允许的范围内。")
        if int(number) > 2147483647:
            raise ValueError
        # Use the configured spelling, not data supplied by the model or URL.
        return IssueTarget(repository=allowed_repository, issue_number=int(number))
    except ValueError:
        raise AppError("invalid_issue_url", "需要 https://github.com/owner/repo/issues/正整数 链接。") from None


class AnalyzeRequest(StrictModel):
    issue_url: str = Field(min_length=1, max_length=500)
    use_knowledge: bool = True
    example_id: str | None = Field(default=None,max_length=60,pattern=r"^[a-z0-9-]+$")


class IssueArgs(IssueTarget):
    pass


class CommentArgs(IssueArgs):
    page: int = Field(default=1, ge=1, le=2)


TextItem = Annotated[str, Field(min_length=1, max_length=800)]


class Analysis(StrictModel):
    summary: str = Field(min_length=1, max_length=1200)
    category: Literal["installation", "dependency", "configuration", "other", "unclear"]
    known_information: list[TextItem] = Field(max_length=12)
    missing_information: list[TextItem] = Field(max_length=12)
    reply_draft: str = Field(min_length=1, max_length=3000)


class Recommendation(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=4)


class KnowledgeAnalysis(Analysis):
    evidence_status: Literal["sufficient", "partial", "insufficient"]
    recommendations: list[Recommendation] = Field(max_length=5)


class ToolTrace(StrictModel):
    call_id: str
    name: str
    arguments: dict = Field(default_factory=dict)
    status: Literal["running", "success", "rejected", "failed", "cancelled", "timed_out"]
    elapsed_ms: float = 0
    result_bytes: int = 0
    error_code: str | None = None


class ErrorInfo(StrictModel):
    code: str
    message: str


from knowledge.models import RetrievalResult


class AnalyzeResponse(StrictModel):
    task_id: str
    status: Literal["completed", "failed", "timed_out", "cancelled"]
    target: IssueTarget | None = None
    analysis: KnowledgeAnalysis | Analysis | None = None
    error: ErrorInfo | None = None
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0
    model_calls: int = 0
    timings_ms: dict[str, float] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)
    usage_reported_calls: int = 0
    documentation_checked: bool = False
    retrieval: RetrievalResult | None = None
    output_validation_errors: list[str] = Field(default_factory=list)
    mode: Literal["live", "offline_demo", "live_tools_demo", "teaching_case"] = "live"
