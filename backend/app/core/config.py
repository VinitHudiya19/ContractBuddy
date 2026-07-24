"""
Application configuration.

All settings are environment-driven (pydantic-settings). Nothing about which
LLM/embedding provider is active is hardcoded in business logic — it is read
from here, so a single `.env` change swaps providers. See `.env.example`.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["local", "openai", "gemini"]
LLMProviderName = Literal["groq", "gemini", "openai", "anthropic", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_env: str = "development"
    log_level: str = "INFO"
    app_name: str = "AI Document Q&A System"

    # ---- Infrastructure ----
    database_url: str = "sqlite+aiosqlite:///./contractbuddy.db"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "document_chunks"

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

    # ---- Providers ----
    embedding_provider: EmbeddingProviderName = "local"
    llm_provider: LLMProviderName = "groq"
    llm_fallback_provider: str = ""  # empty = no fallback

    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # ---- Retrieval tuning ----
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 50
    vector_top_k: int = 15
    keyword_top_k: int = 15
    rerank_top_k: int = 5

    # ---- Rate limiting ----
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # ---- Bootstrap admin ----
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "admin12345"

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so `.env` is parsed once per process."""
    return Settings()


settings = get_settings()
