"""
Application settings loaded from environment variables / .env file.

Two deployment shapes are supported and share the same settings class:

``server`` (default)
    The Docker Compose stack: PostgreSQL for relational data, a ChromaDB HTTP
    container for vectors, and the nginx container serving the SPA. Every path
    below defaults to the container mount point.

``embedded`` (``RAGVAULT_EMBEDDED=1``)
    The desktop build: one process, no containers. SQLite replaces PostgreSQL,
    ``PersistentClient`` replaces the Chroma HTTP server, and every mutable path
    moves under a single ``--data-dir`` that the Tauri shell owns. The API also
    serves the built SPA so the window can talk to ``http://127.0.0.1:PORT``
    (see ``docs/desktop-packaging.md``).

Embedded mode only rewrites a path when it is still on its server default, so
an explicit environment variable always wins.
"""
from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Server-mode defaults (the Docker Compose stack) ───────────────────────────
_DEFAULT_DB_URL = "postgresql+asyncpg://knowledge_user:changeme_strong_password@postgres:5432/knowledge_hub"
_DEFAULT_CHROMA_PERSIST_DIR = "/chroma_data"
_DEFAULT_UPLOAD_TEMP_DIR = "/uploads/temp"
_DEFAULT_HF_HOME = "/hf_cache"

# ── Embedded-mode defaults (relative to the data directory) ───────────────────
_EMBEDDED_DB_FILENAME = "ragvault.db"
_EMBEDDED_CHROMA_DIRNAME = "chroma"
_EMBEDDED_UPLOADS_DIRNAME = "uploads"
_EMBEDDED_MODELS_DIRNAME = "models"
# Uploads are streamed to disk in 1 MB chunks, but the parser still holds one
# whole document in memory; 500 MB is a safe ceiling on a 8-16 GB laptop.
_EMBEDDED_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class Settings(BaseSettings):
    # ── Deployment shape ──────────────────────────────────────────────────────
    # "1"/"true" switches on the single-process desktop layout described above.
    embedded: bool = False
    # Root of all mutable state in embedded mode (Windows: %APPDATA%\RagVault).
    # Empty means "current working directory", which is only sensible in tests.
    data_dir: str = ""
    # Directory holding the built SPA (index.html + assets). When it exists the
    # API mounts it at "/" and serves index.html for unknown paths, so the
    # desktop window and a plain browser share one origin.
    web_dist_dir: str = ""

    # ── Relational database ───────────────────────────────────────────────────
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
    # "server" probes the HTTP container; "embedded" goes straight to
    # PersistentClient and skips the heartbeat (saves 1-2s of startup time).
    chroma_mode: str = "server"
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_persist_dir: str = _DEFAULT_CHROMA_PERSIST_DIR

    # ── File Storage ──────────────────────────────────────────────────────────
    upload_temp_dir: str = _DEFAULT_UPLOAD_TEMP_DIR
    # Hard cap for a single upload. The desktop build lowers this because the
    # file is streamed into memory-adjacent temp space on a user laptop.
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024

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
    hf_home: str = _DEFAULT_HF_HOME

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return _DEFAULT_DB_URL
        return str(v)

    @model_validator(mode="after")
    def apply_embedded_defaults(self) -> "Settings":
        """Rewrite container paths to data-dir paths when embedded mode is on."""
        if not self.embedded:
            return self

        root = Path(self.data_dir).expanduser() if self.data_dir else Path.cwd()

        if self.database_url == _DEFAULT_DB_URL:
            db_path = root / _EMBEDDED_DB_FILENAME
            # as_posix() keeps Windows backslashes out of the SQLite URL.
            self.database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        if self.chroma_mode == "server":
            self.chroma_mode = "embedded"
        if self.chroma_persist_dir == _DEFAULT_CHROMA_PERSIST_DIR:
            self.chroma_persist_dir = str(root / _EMBEDDED_CHROMA_DIRNAME)
        if self.upload_temp_dir == _DEFAULT_UPLOAD_TEMP_DIR:
            self.upload_temp_dir = str(root / _EMBEDDED_UPLOADS_DIRNAME / "temp")
        if self.hf_home == _DEFAULT_HF_HOME:
            self.hf_home = str(root / _EMBEDDED_MODELS_DIRNAME)
        # A laptop is not a server: 2 GB single files push the process into swap
        # while the PDF parser holds the whole document in memory.
        if self.max_upload_bytes > _EMBEDDED_MAX_UPLOAD_BYTES:
            self.max_upload_bytes = _EMBEDDED_MAX_UPLOAD_BYTES

        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return singleton Settings instance (cached after first call)."""
    # The desktop launcher sets RAGVAULT_ENV_FILE="" so the developer's Docker
    # `.env` (Postgres URL, container paths) cannot leak into a desktop profile.
    env_file = os.environ.get("RAGVAULT_ENV_FILE", ".env").strip()
    return Settings(_env_file=env_file or None)
