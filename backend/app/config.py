from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "知域企业知识库"
    app_env: str = os.getenv("APP_ENV", "development").lower()
    demo_mode: bool = _env_bool("DEMO_MODE", True)
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-this-secret")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "480"))
    database_path: Path = PROJECT_ROOT / os.getenv(
        "DATABASE_PATH", "backend/data/knowledge.db"
    )
    upload_dir: Path = PROJECT_ROOT / os.getenv(
        "UPLOAD_DIR", "backend/data/uploads"
    )
    upload_session_dir: Path = PROJECT_ROOT / os.getenv(
        "UPLOAD_SESSION_DIR", "backend/data/upload_sessions"
    )
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    max_chunked_upload_bytes: int = int(
        os.getenv("MAX_CHUNKED_UPLOAD_BYTES", str(512 * 1024 * 1024))
    )
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
    ollama_base_url: str = os.getenv(
        "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
    ).rstrip("/")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv(
        "LLM_BASE_URL", "https://api.openai.com/v1"
    ).rstrip("/")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "384"))
    vector_min_similarity: float = float(os.getenv("VECTOR_MIN_SIMILARITY", "0.40"))
    vector_store: str = os.getenv("VECTOR_STORE", "sqlite").lower()
    chroma_path: Path = PROJECT_ROOT / os.getenv("CHROMA_PATH", "backend/data/chroma")
    pgvector_dsn: str = os.getenv(
        "PGVECTOR_DSN", "postgresql://knowledge:knowledge@127.0.0.1:5432/knowledge"
    )
    pgvector_dimensions: int = int(os.getenv("PGVECTOR_DIMENSIONS", "1024"))
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
    model_timeout_seconds: float = float(os.getenv("MODEL_TIMEOUT_SECONDS", "90"))
    model_max_retries: int = int(os.getenv("MODEL_MAX_RETRIES", "2"))
    rate_limit_enabled: bool = _env_bool("RATE_LIMIT_ENABLED", True)
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "600"))
    rate_limit_burst: int = int(os.getenv("RATE_LIMIT_BURST", "50"))
    task_queue: str = os.getenv("TASK_QUEUE", "inline").lower()
    task_timeout_seconds: int = int(os.getenv("TASK_TIMEOUT_SECONDS", "900"))
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
    audit_log_queries: bool = _env_bool("AUDIT_LOG_QUERIES", False)
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if item.strip()
    )

    def validate_runtime(self) -> None:
        if self.llm_provider not in {"ollama", "openai", "disabled"}:
            raise RuntimeError("LLM_PROVIDER 仅支持 ollama、openai 或 disabled")
        if self.embedding_provider not in {"ollama", "openai", "local"}:
            raise RuntimeError("EMBEDDING_PROVIDER 仅支持 ollama、openai 或 local")
        if self.vector_store not in {"sqlite", "chroma", "pgvector"}:
            raise RuntimeError("VECTOR_STORE 仅支持 sqlite、chroma 或 pgvector")
        if self.task_queue not in {"inline", "celery"}:
            raise RuntimeError("TASK_QUEUE 仅支持 inline 或 celery")
        if self.rate_limit_per_minute < 1 or self.rate_limit_burst < 1:
            raise RuntimeError("限流参数必须为正整数")
        if self.app_env == "production":
            if self.demo_mode:
                raise RuntimeError("生产环境必须设置 DEMO_MODE=false")
            if len(self.jwt_secret) < 32 or self.jwt_secret in {
                "dev-only-change-this-secret",
                "replace-before-production",
                "replace-with-a-long-random-secret",
            }:
                raise RuntimeError("生产环境必须配置至少 32 字符的独立 JWT_SECRET")
            if self.embedding_provider == "local":
                raise RuntimeError("生产环境不能使用 local 特征哈希向量")
        if self.llm_provider == "openai" and not self.llm_api_key:
            raise RuntimeError("LLM_PROVIDER=openai 时必须配置 LLM_API_KEY")
        if self.embedding_provider == "openai" and not self.llm_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai 时必须配置 LLM_API_KEY")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_session_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    return settings
