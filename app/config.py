from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    allowed_repository: str = Field(
        default="YYB367/learning-mcp-server",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$",
    )
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = Field(default="deepseek-flash", min_length=1, max_length=100)
    deepseek_base_url: str = "https://api.deepseek.com"
    github_token: SecretStr = SecretStr("")
    github_writes_enabled: bool = False
    task_timeout_seconds: float = Field(default=90, gt=0, le=300)
    github_timeout_seconds: float = Field(default=10, gt=0, le=30)
    model_timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_tool_calls: int = Field(default=6, ge=2, le=10)
    max_model_calls: int = Field(default=8, ge=3, le=12)
    knowledge_enabled: bool = True
    knowledge_path: Path = PROJECT_ROOT / "work" / "knowledge"
    embedding_model_path: Path = PROJECT_ROOT / "work" / "models" / "bge-small-zh"
    retrieval_top_k: int = Field(default=3, ge=1, le=5)
    retrieval_max_distance: float = Field(default=0.40, ge=0, le=2)
    history_top_k: int = Field(default=2, ge=1, le=3)
    history_max_distance: float = Field(default=0.30, ge=0, le=2)
    keyword_fallback_enabled: bool = True
    state_db_path: Path = PROJECT_ROOT / "work" / "sessions-v4.sqlite3"
    auto_backup_enabled: bool = True
    launch_port: int = Field(default=8008,ge=1024,le=65535)

    @property
    def backup_directory(self) -> Path:
        return self.state_db_path.parent / "backups"

    @property
    def restore_hold_path(self) -> Path:
        return self.state_db_path.with_suffix(".restore-hold.json")

    log_path: Path = PROJECT_ROOT / "work" / "logs" / "events.jsonl"

    @field_validator("state_db_path", "log_path", "knowledge_path", "embedding_model_path")
    @classmethod
    def project_relative_paths(cls,value: Path) -> Path:
        return (value if value.is_absolute() else PROJECT_ROOT/value).resolve()

    @field_validator("deepseek_base_url")
    @classmethod
    def trusted_model_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment):
            raise ValueError("Model base URL must be an HTTPS endpoint without credentials/query")
        return value.rstrip("/")


# Fixed resource limits. They are not model arguments.
COMMENTS_PER_PAGE = 10
MAX_COMMENT_PAGES = 2
ISSUE_BODY_CHARS = 6000
COMMENT_BODY_CHARS = 1200
TOOL_RESULT_BYTES = 24000
GITHUB_RESPONSE_BYTES = 512000
CONTEXT_BYTES = 100000
MODEL_OUTPUT_TOKENS = 2200
EMBEDDING_TOKEN_LIMIT = 384
RETRIEVAL_CONTEXT_BYTES = 16000
RETRIEVAL_TOKEN_ESTIMATE_LIMIT = 2200
