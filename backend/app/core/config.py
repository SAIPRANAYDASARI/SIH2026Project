"""Application settings.

Single source of truth for configuration, loaded once from the process
environment (see `.env.example` for the documented list of variables) and
exposed as a cached `Settings` singleton via `get_settings()`. No module in
this codebase should read `os.environ` directly outside this file — that
keeps every configurable knob discoverable in one place, which matters a lot
on demo day when someone needs to flip LLM_BACKEND from `ollama` to `hosted`
(or back) without hunting through the codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "manak-sahayak"
    app_secret_key: str = "insecure-dev-key-change-me"
    app_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"
    log_level: str = "INFO"

    # --- Postgres ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "manak_sahayak"
    postgres_user: str = "manak"
    postgres_password: str = "change-me"
    database_url: str | None = None

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str | None = None

    # --- Celery ---
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- LLM adapter ---
    llm_backend: Literal["ollama", "hosted"] = "ollama"
    # "openai" means "speaks the OpenAI chat/completions wire format", not
    # literally OpenAI's own API — that covers OpenAI itself, NVIDIA NIM
    # (https://integrate.api.nvidia.com/v1), Azure OpenAI, Groq, Together,
    # and most other hosted inference providers via `hosted_llm_base_url`.
    # See docs/DECISIONS.md, Step 5.
    hosted_llm_provider: Literal["anthropic", "openai"] = "openai"
    hosted_llm_api_key: str = ""
    hosted_llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    hosted_llm_model: str = "meta/llama-3.1-70b-instruct"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "bge-m3"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.2

    # --- Retrieval ---
    embedding_dim: int = 1024
    rrf_k: int = 60
    rerank_top_k: int = 8
    sparse_candidate_k: int = 50
    dense_candidate_k: int = 50
    reranker_base_url: str = "http://reranker:7997"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # --- Auth ---
    jwt_secret_key: str = "insecure-dev-jwt-key-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    session_cookie_name: str = "ms_session"
    session_cookie_secure: bool = False

    # --- Rate limiting ---
    rate_limit_per_minute_anon: int = 20
    rate_limit_per_minute_auth: int = 60

    # --- CORS ---
    cors_allowed_origins: str = "http://localhost:5173"

    # --- Blob storage ---
    blob_store_path: str = "/data/blobs"

    # --- Seed data ---
    seed_demo_data: bool = False

    # --- Translation adapter (Step 10) ---
    # "none" is the default so the whole system works fully offline with no
    # external call; Bhashini (https://bhashini.gov.in) is India's
    # government multilingual API and the only real backend implemented —
    # see docs/DECISIONS.md, Step 10. ASK THE USER for these credentials;
    # never hardcode or commit a real key.
    translation_backend: Literal["none", "bhashini"] = "none"
    bhashini_api_key: str = ""
    bhashini_user_id: str = ""
    bhashini_base_url: str = "https://meity-auth.ulcacontrib.org"
    bhashini_pipeline_id: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_uri(self) -> str:
        if self.redis_url:
            return self.redis_url
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first call)."""
    return Settings()
