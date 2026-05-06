from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingDevice = Literal["auto", "cuda", "cpu"]
EmbeddingBackend = Literal["auto", "sentence-transformers", "hashing"]
RerankBackend = Literal["auto", "flag", "lexical", "none"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek_api_key: SecretStr | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    researchmate_llm_model: str = Field(
        default="deepseek/deepseek-chat",
        alias="RESEARCHMATE_LLM_MODEL",
    )

    oss_access_key_id: str | None = Field(default=None, alias="OSS_ACCESS_KEY_ID")
    oss_access_key_secret: SecretStr | None = Field(
        default=None,
        alias="OSS_ACCESS_KEY_SECRET",
    )
    oss_bucket: str | None = Field(default=None, alias="OSS_BUCKET")
    oss_endpoint: str | None = Field(default=None, alias="OSS_ENDPOINT")
    oss_local_dir: Path = Field(default=Path("./data/oss"), alias="OSS_LOCAL_DIR")
    oss_cache_dir: Path = Field(default=Path("./data/cache"), alias="OSS_CACHE_DIR")

    research_agent_token: SecretStr = Field(
        default=SecretStr("change-me-to-a-random-token-with-at-least-32-chars"),
        alias="RESEARCH_AGENT_TOKEN",
        min_length=32,
    )
    research_agent_bind: str = Field(default="127.0.0.1:8000", alias="RESEARCH_AGENT_BIND")
    adk_session_db_url: str = Field(
        default="sqlite+aiosqlite:///./data/sessions.db",
        alias="ADK_SESSION_DB_URL",
    )
    embedding_device: EmbeddingDevice = Field(default="auto", alias="EMBEDDING_DEVICE")
    embedding_backend: EmbeddingBackend = Field(default="auto", alias="EMBEDDING_BACKEND")
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_allow_download: bool = Field(default=False, alias="EMBEDDING_ALLOW_DOWNLOAD")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE", ge=1, le=512)
    rerank_backend: RerankBackend = Field(default="auto", alias="RERANK_BACKEND")
    reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANKER_MODEL")
    rerank_allow_download: bool = Field(default=False, alias="RERANK_ALLOW_DOWNLOAD")
    chroma_dir: Path = Field(default=Path("./data/chroma"), alias="CHROMA_DIR")
    kb_collection: str = Field(default="kb_chunks", alias="KB_COLLECTION")
    memory_collection: str = Field(default="memory_records", alias="MEMORY_COLLECTION")
    jobs_db_path: Path = Field(default=Path("./data/jobs.db"), alias="JOBS_DB_PATH")
    papers_db_path: Path = Field(default=Path("./data/papers.db"), alias="PAPERS_DB_PATH")
    memory_idle_archive_seconds: int = Field(
        default=1800,
        alias="MEMORY_IDLE_ARCHIVE_SECONDS",
        ge=60,
    )
    memory_idle_scan_seconds: int = Field(
        default=300,
        alias="MEMORY_IDLE_SCAN_SECONDS",
        ge=30,
    )
    memory_max_session_facts: int = Field(
        default=8,
        alias="MEMORY_MAX_SESSION_FACTS",
        ge=1,
        le=50,
    )
    rag_dense_k: int = Field(default=20, alias="RAG_DENSE_K", ge=1, le=200)
    rag_sparse_k: int = Field(default=20, alias="RAG_SPARSE_K", ge=1, le=200)
    rag_final_k: int = Field(default=5, alias="RAG_FINAL_K", ge=1, le=50)

    @field_validator("research_agent_bind")
    @classmethod
    def validate_bind(cls, value: str) -> str:
        host, separator, port = value.rpartition(":")
        if not host or separator != ":":
            msg = "RESEARCH_AGENT_BIND must be formatted as host:port"
            raise ValueError(msg)
        if not port.isdigit() or not (0 < int(port) < 65536):
            msg = "RESEARCH_AGENT_BIND port must be between 1 and 65535"
            raise ValueError(msg)
        return value

    @field_validator("research_agent_token")
    @classmethod
    def validate_agent_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            msg = "RESEARCH_AGENT_TOKEN must contain at least 32 characters"
            raise ValueError(msg)
        return value

    @field_validator("adk_session_db_url")
    @classmethod
    def validate_session_db_url(cls, value: str) -> str:
        if not value.startswith("sqlite+aiosqlite:///"):
            msg = "ADK_SESSION_DB_URL must be a SQLAlchemy aiosqlite URL"
            raise ValueError(msg)
        return value

    @field_validator("kb_collection")
    @classmethod
    def validate_collection_name(cls, value: str) -> str:
        if not value.strip():
            msg = "KB_COLLECTION must not be empty"
            raise ValueError(msg)
        return value.strip()

    @field_validator("memory_collection")
    @classmethod
    def validate_memory_collection_name(cls, value: str) -> str:
        if not value.strip():
            msg = "MEMORY_COLLECTION must not be empty"
            raise ValueError(msg)
        return value.strip()

    @property
    def bind_host(self) -> str:
        return self.research_agent_bind.rsplit(":", maxsplit=1)[0]

    @property
    def bind_port(self) -> int:
        return int(self.research_agent_bind.rsplit(":", maxsplit=1)[1])

    @property
    def session_db_path(self) -> Path:
        return Path(self.adk_session_db_url.removeprefix("sqlite+aiosqlite:///"))

    @property
    def has_deepseek_api_key(self) -> bool:
        if self.deepseek_api_key is None:
            return False
        return bool(self.deepseek_api_key.get_secret_value().strip())

    @property
    def has_oss_credentials(self) -> bool:
        if not self.oss_access_key_id or not self.oss_bucket or not self.oss_endpoint:
            return False
        if self.oss_access_key_secret is None:
            return False
        return bool(self.oss_access_key_secret.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(override=False)
    return Settings()
