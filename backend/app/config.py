"""
Application settings loaded from environment variables / .env file.

RagVault is a Windows desktop application: one process, no containers. SQLite
holds the relational data, an embedded Chroma store (``PersistentClient``)
holds the vectors, and every mutable path lives under a single data directory
that the Tauri shell owns (``%APPDATA%\\RagVault`` unless ``--data-dir`` says
otherwise). The API also serves the built SPA, so the native window can talk to
``http://127.0.0.1:PORT`` (see ``docs/desktop-packaging.md``).

Paths are derived from ``data_dir`` at construction time; an explicit
environment variable always wins over the derived default.
"""
from functools import lru_cache
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ── Directory names under the data directory ──────────────────────────────────
_DB_FILENAME = "ragvault.db"
_CHROMA_DIRNAME = "chroma"
_UPLOADS_DIRNAME = "uploads"
_MODELS_DIRNAME = "models"

#: Per-install JWT signing key. Lives in the data directory, never in the repo:
#: a key baked into the binary would let anyone mint a token for any install.
_JWT_SECRET_FILENAME = ".jwt_secret"

#: The placeholder that used to ship in ``.env``. Treated as "not configured":
#: seeing it means this install has no real key yet, so one is generated.
_INSECURE_JWT_SECRET = "change_this_to_a_long_random_secret_key_at_least_32_chars"

#: Shortest key we accept. HS256 keys shorter than the 256-bit output weaken the
#: MAC, and a truncated hand-edited value should be regenerated rather than used.
_MIN_JWT_SECRET_LENGTH = 32

# Uploads are streamed to disk in 1 MB chunks, but the parser still holds one
# whole document in memory; 500 MB is a safe ceiling on a 8-16 GB laptop.
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _read_jwt_secret_file(path: Path) -> str:
    """Return the stored key, or "" when the file is missing/unusable."""
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("[config] cannot read %s (%s); a new key will be generated", path, exc)
        return ""
    if len(existing) < _MIN_JWT_SECRET_LENGTH:
        logger.warning(
            "[config] %s holds a %d-character key (minimum %d); regenerating it",
            path,
            len(existing),
            _MIN_JWT_SECRET_LENGTH,
        )
        return ""
    return existing


def _write_jwt_secret_file(path: Path, secret: str) -> bool:
    """Persist the key owner-readable-only where the filesystem supports it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 0o600 is honoured on POSIX and ignored on Windows (NTFS ACLs apply).
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret + "\n")
        return True
    except OSError as exc:
        logger.warning("[config] cannot write %s (%s)", path, exc)
        return False


def load_or_create_jwt_secret(root: Path) -> str:
    """Read ``<root>/.jwt_secret``, creating it with a fresh random key if absent.

    Returns "" only when the file cannot be written, in which case the caller
    keeps whatever was configured — a read-only data directory must not stop the
    application from starting.
    """
    path = root / _JWT_SECRET_FILENAME
    existing = _read_jwt_secret_file(path)
    if existing:
        return existing

    secret = secrets.token_urlsafe(48)
    if not _write_jwt_secret_file(path, secret):
        return ""
    logger.info("[config] generated a new JWT signing key at %s", path)
    return secret


class Settings(BaseSettings):
    # ── Data directory ────────────────────────────────────────────────────────
    # Root of all mutable state (Windows: %APPDATA%\RagVault). Empty means "the
    # current working directory", which is only sensible in tests.
    data_dir: str = ""
    # Directory holding the built SPA (index.html + assets). When it exists the
    # API mounts it at "/" and serves index.html for unknown paths, so the
    # desktop window and a plain browser share one origin.
    web_dist_dir: str = ""

    # ── Relational database ───────────────────────────────────────────────────
    # Empty means "the SQLite file inside data_dir"; the validator below fills
    # it in so the URL always points at the active profile.
    database_url: str = ""

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    # Leaving this empty is the normal case: the validator below generates a
    # random key once and stores it in ``<data_dir>/.jwt_secret``, so every
    # install signs with its own secret and no default lives in the source tree.
    # Set JWT_SECRET only to force a shared key (tests, a server deployment).
    jwt_secret: str = ""
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

    # ── ChromaDB (embedded PersistentClient) ──────────────────────────────────
    # Empty means "<data_dir>/chroma"; the validator below fills it in.
    chroma_persist_dir: str = ""

    # ── File Storage ──────────────────────────────────────────────────────────
    upload_temp_dir: str = ""
    max_upload_bytes: int = _MAX_UPLOAD_BYTES

    # ── RAG / Chunking ────────────────────────────────────────────────────────
    chunk_size: int = 600
    chunk_overlap: int = 100
    top_k: int = 5
    rag_max_distance: float = 0.38

    # ── Shelved capabilities ──────────────────────────────────────────────────
    # Audio/video transcription (was local Faster-Whisper) is parked for now. The
    # parser code is kept so it can be re-enabled later without rewriting
    # anything: flip the flag back to true and install the optional dependencies
    # listed in backend/requirements.txt.
    enable_audio_video_uploads: bool = False

    # ── PDF parsing pipeline ──────────────────────────────────────────────────
    # Scanned PDFs are read with a local OCR engine (RapidOCR, ONNX). This is on
    # by default because a scanned PDF with OCR disabled produces almost no text
    # and the user has no way to tell why their answers are bad. Set to false to
    # keep uploads fast and refuse OCR entirely.
    enable_ocr_uploads: bool = True

    #: ``auto`` prefers RapidOCR (self-contained) and falls back to Tesseract.
    pdf_ocr_engine: str = "auto"
    #: Render resolution. 300 DPI is the sweet spot: measured on real scans, the
    #: recognised character count is essentially identical at 200-400 DPI, so
    #: higher values only burn CPU.
    pdf_ocr_dpi: int = 300
    #: Longest side of the rendered page, in pixels. Downscaling a 300 DPI A4
    #: render to 1600px costs nothing in accuracy and roughly halves OCR time.
    pdf_ocr_max_side: int = 1600
    #: Hard cap on how many pages may be OCR'd per document (0 = no cap). A
    #: 1400-page scan needs hours of CPU, so the safe answer is a budget rather
    #: than unbounded work.
    pdf_ocr_max_pages: int = 0
    #: onnxruntime intra-op threads per OCR engine. Defaults to 8 rather than
    #: "one per core": measured on a 16-core machine, the library default took
    #: 12.4s/page and 8 threads took 7.5s/page for identical output. Capping
    #: threads beats oversubscribing them. Set 0 to let the library decide.
    pdf_ocr_threads: int = 8
    #: Wall-clock ceiling for the OCR stage, in seconds. The remaining pages are
    #: reported as unread instead of blocking the worker forever.
    pdf_ocr_time_budget_seconds: int = 1800
    #: Mean per-block confidence below which a page is flagged for review.
    pdf_ocr_min_confidence: float = 0.75
    #: How many preprocessing variants to try per page before giving up.
    pdf_ocr_max_attempts: int = 3
    #: A page whose text layer is shorter than this, while being covered by a
    #: page-sized image, is treated as a scan rather than as real text.
    pdf_min_text_chars: int = 200
    #: Extract ruled tables as Markdown so their structure survives chunking.
    pdf_extract_tables: bool = True

    # ── Internationalisation ──────────────────────────────────────────────────
    # Default UI + AI output language: "en" or "zh".
    # The SPA can override this per browser session (language switcher), and the
    # override is sent to the API through the ``X-App-Language`` header.
    app_language: str = "en"

    # ── Runtime ───────────────────────────────────────────────────────────────
    environment: str = "production"
    log_level: str = "INFO"

    # ── HuggingFace Cache ─────────────────────────────────────────────────────
    # Empty means "<data_dir>/models".
    hf_home: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: Any) -> str:
        # Only SQLite is supported: the app always runs as a single process, so
        # a server database would have nothing to serve it.
        value = str(v or "").strip()
        if value and not value.startswith("sqlite"):
            raise ValueError(
                "DATABASE_URL must be a SQLite URL (sqlite+aiosqlite:///…); "
                "RagVault runs as a single desktop process with no database server"
            )
        return value

    @model_validator(mode="after")
    def apply_data_dir_defaults(self) -> "Settings":
        """Derive every path from ``data_dir`` unless it was set explicitly."""
        root = Path(self.data_dir).expanduser() if self.data_dir else Path.cwd()

        if not self.database_url:
            db_path = root / _DB_FILENAME
            # as_posix() keeps Windows backslashes out of the SQLite URL.
            self.database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        if not self.chroma_persist_dir:
            self.chroma_persist_dir = str(root / _CHROMA_DIRNAME)
        if not self.upload_temp_dir:
            self.upload_temp_dir = str(root / _UPLOADS_DIRNAME / "temp")
        if not self.hf_home:
            self.hf_home = str(root / _MODELS_DIRNAME)

        # ── Per-install JWT signing key ───────────────────────────────────────
        # An explicit, non-placeholder JWT_SECRET wins (tests and a server
        # deployment need a shared key). Otherwise the key comes from
        # ``<data_dir>/.jwt_secret``, generated on first start: a secret shipped
        # inside the installer would let anyone forge a token for any install.
        configured = (self.jwt_secret or "").strip()
        if configured and configured != _INSECURE_JWT_SECRET:
            if len(configured) < _MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET must be at least {_MIN_JWT_SECRET_LENGTH} characters; "
                    "leave it empty to let the app generate one per install"
                )
            self.jwt_secret = configured
        else:
            generated = load_or_create_jwt_secret(root)
            if generated:
                self.jwt_secret = generated
            else:
                # Last resort: the data directory is read-only. Keep the process
                # usable for this run rather than refusing to start, but say so
                # loudly — tokens will not survive a restart.
                logger.error(
                    "[config] no writable data directory (%s): using an ephemeral JWT "
                    "key, so existing sessions will be invalidated on restart",
                    root,
                )
                self.jwt_secret = secrets.token_urlsafe(48)

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return singleton Settings instance (cached after first call)."""
    # The desktop launcher sets RAGVAULT_ENV_FILE="" so a developer's `.env`
    # (an API key, a language override) cannot leak into a packaged profile.
    env_file = os.environ.get("RAGVAULT_ENV_FILE", ".env").strip()
    return Settings(_env_file=env_file or None)
