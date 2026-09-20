"""
Application configuration.

Everything comes from the environment (pydantic-settings), with defaults that
let the app run on a clean checkout. See `.env.example`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py → core → app → backend → repo root
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

# Absolute paths so settings do not change depending on which directory the
# process was launched from. Later files win, so the repo-root `.env` is the
# single source of truth; `backend/.env` is only a legacy fallback.
_ENV_FILES = (_BACKEND_DIR / ".env", _REPO_ROOT / ".env")

VectorStoreName = Literal["auto", "qdrant", "sql"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_env: str = "development"
    log_level: str = "INFO"
    app_name: str = "Contract Buddy"

    # ---- Infrastructure ----
    database_url: str = "sqlite+aiosqlite:///./contractbuddy.db"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "document_chunks"
    # auto = use Qdrant when reachable, else the built-in SQL vector store.
    vector_store: VectorStoreName = "auto"

    # ---- Auth ----
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ---- CORS ----
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000,*"

    # ---- Uploads ----
    max_upload_size_mb: int = 20
    upload_dir: str = "storage"

    # ---- Models ----
    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    # Generous enough for a long answer, short enough that a stuck call fails
    # instead of pinning the worker until the client gives up.
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---- Retrieval tuning ----
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 50
    vector_top_k: int = 15
    keyword_top_k: int = 15
    rerank_top_k: int = 5
    rerank_enabled: bool = True

    # ---- Rate limiting ----
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _reject_insecure_production_defaults(self) -> Settings:
        """Don't let production start with the dev defaults still in place."""
        if not self.is_production:
            return self

        problems = []
        if self.jwt_secret == "change-me":
            problems.append("JWT_SECRET is still the default, so anyone can forge tokens")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS contains '*'; list your real frontend origin")
        if problems:
            raise ValueError(
                "Refusing to start with APP_ENV=production:\n  - "
                + "\n  - ".join(problems)
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def resolved_database_url(self) -> str:
        """
        Same database no matter where the process was started from.

        A relative SQLite path (`sqlite+aiosqlite:///./app.db`) resolves against
        the current working directory, which silently creates a second, empty
        database when the app is launched from a different folder. Anchor it to
        the backend package instead.
        """
        url = self.database_url
        prefix, sep, path = url.partition(":///")
        if not sep or not prefix.startswith("sqlite") or path.startswith("/"):
            return url
        if path == ":memory:" or path.startswith(":memory:"):
            return url
        return f"{prefix}:///{(_BACKEND_DIR / path).resolve().as_posix()}"

    @property
    def upload_path(self) -> Path:
        """Absolute staging directory for in-flight uploads."""
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = _BACKEND_DIR / path
        return path

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so `.env` is parsed once per process."""
    return Settings()


settings = get_settings()
