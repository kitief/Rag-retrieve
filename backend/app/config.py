"""
Application settings loaded from environment variables.
All values can be overridden via .env file or environment variables.
"""
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DB_URL = "postgresql+asyncpg://knowledge_user:changeme_strong_password@postgres:5432/knowledge_hub"


class Settings(BaseSettings):
    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url: str = _DEFAULT_DB_URL

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    jwt_secret: str = "change_this_to_a_long_random_secret_key_at_least_32_chars"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # ── Cloud LLM (OpenAI-compatible Chat Completions API) ────────────────────
    # provider: deepseek | openai | custom
    # Empty base_url / model fall back to the preset of the selected provider.
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 3
    llm_max_concurrency: int = 4

    # ── Embeddings (local FastEmbed / ONNX) ───────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_fallback_model: str = "nomic-embed-text"

    # ── ChromaDB ─────────────────────────────────────────────────────────────
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_persist_dir: str = "/chroma_data"

    # ── File Storage ──────────────────────────────────────────────────────────
    upload_temp_dir: str = "/uploads/temp"

    # ── RAG / Chunking ────────────────────────────────────────────────────────
    chunk_size: int = 600
    chunk_overlap: int = 100
    top_k: int = 5
    rag_max_distance: float = 0.38

    # ── Shelved capabilities ──────────────────────────────────────────────────
    # Audio/video transcription (was local Faster-Whisper) and image/scanned-PDF
    # OCR (was local Tesseract) are parked for now. The parser code is kept so
    # they can be re-enabled later without rewriting anything: flip these flags
    # back to true and optionally point the transcribers at a cloud API.
    enable_audio_video_uploads: bool = False
    enable_ocr_uploads: bool = False

    # ── Internationalisation ──────────────────────────────────────────────────
    # Default UI + AI output language: "en" or "zh".
    # The SPA can override this per browser session (language switcher), and the
    # override is sent to the API through the ``X-App-Language`` header.
    app_language: str = "en"

    # ── Runtime ───────────────────────────────────────────────────────────────
    environment: str = "production"
    log_level: str = "INFO"

    # ── HuggingFace Cache ─────────────────────────────────────────────────────
    hf_home: str = "/hf_cache"

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return _DEFAULT_DB_URL
        return str(v)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return singleton Settings instance (cached after first call)."""
    return Settings()
