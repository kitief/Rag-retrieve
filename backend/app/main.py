"""
FastAPI application entry point.
Mounts all routers, configures CORS, and handles startup/shutdown lifecycle.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core import i18n
from app.core.spa import mount_spa
from app.database import create_tables
from app.routers.auth import router as auth_router
from app.routers.chats import router as chats_router
from app.routers.documents import router as documents_router
from app.routers.messages import router as messages_router
from app.routers.quiz import router as quiz_router
from app.routers.notes import router as notes_router
from app.routers.settings import router as settings_router

# Reported by /health and /config, and shown in the OpenAPI schema.
API_VERSION = "2.1.0"

# Written by the Tauri shell when it spawns this process; the guard below stays
# disabled when it is empty (tests, a bare backend-only dev run).
LOCAL_TOKEN = os.environ.get("RAGVAULT_LOCAL_TOKEN", "").strip()
LOCAL_TOKEN_HEADER = b"x-ragvault-token"
# Paths a browser can reach without the token: the readiness probe (used by the
# shell before the window exists) and the OpenAPI docs.
_TOKEN_EXEMPT = frozenset({"/health"})

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/health") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    cfg = get_settings()

    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting RagVault API (env=%s)", cfg.environment)

    # Create database tables
    await create_tables()
    logger.info("Database tables initialized successfully.")

    # Load the overrides saved from the settings dialog so the very first
    # request already sees them (they win over the .env values).
    from app.core import runtime_settings
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stored_settings = await runtime_settings.load_from_db(session)
    if stored_settings:
        logger.info(
            "Runtime overrides loaded from the settings dialog: %s",
            ", ".join(sorted(stored_settings)),
        )

    # Create temp upload directory
    os.makedirs(cfg.upload_temp_dir, exist_ok=True)
    logger.info("Upload temp dir: %s", cfg.upload_temp_dir)

    # Every mutable path lives under one data directory (see app/config.py).
    logger.info(
        "Data directory: %s (database=%s, chroma=%s)",
        cfg.data_dir or os.getcwd(),
        cfg.database_url,
        cfg.chroma_persist_dir,
    )

    # Probe the configured cloud LLM in the background (never blocks startup).
    import asyncio
    from app.services import llm_client
    logger.info("Cloud LLM: %s", llm_client.describe_llm_setup())
    asyncio.create_task(llm_client.check_llm_availability())

    logger.info(
        "Default language: %s (supported: %s; override per browser via the language switcher)",
        i18n.configured_language(),
        ", ".join(i18n.SUPPORTED_LANGUAGES),
    )

    # NOTE: Embedding model and ChromaDB load lazily on first request.
    logger.info("API startup complete — ready to accept requests.")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down RagVault API")


# ─── App Instance ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="RagVault API",
    description=(
        "RAG-based learning system. "
        "Upload PDF and PPTX files, then chat with your documents. "
        "Answer generation is served by a cloud LLM over an OpenAI-compatible API."
    ),
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:80",
        "http://frontend",
        "http://frontend:80",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request language ─────────────────────────────────────────────────────────

class LanguageMiddleware:
    """
    Bind the request language for the whole lifetime of the response.

    The SPA sends the language the user picked in the UI through the
    ``X-App-Language`` header; when the header is absent (curl, health checks,
    background jobs) the ``APP_LANGUAGE`` default from the environment applies.

    This is deliberately written as a raw ASGI middleware instead of a
    ``BaseHTTPMiddleware``: SSE streams are consumed *after* a
    ``BaseHTTPMiddleware`` returns, which would reset the context variable too
    early and leave streamed answers in the wrong language.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_language: str | None = None
        for key, value in scope.get("headers") or []:
            if key == b"x-app-language":
                try:
                    raw_language = value.decode("latin-1")
                except Exception:
                    raw_language = None
                break

        token = i18n.set_current_language(raw_language)
        try:
            await self.app(scope, receive, send)
        finally:
            i18n.reset_language(token)


app.add_middleware(LanguageMiddleware)


# ─── Desktop local API guard ──────────────────────────────────────────────────

class DesktopLocalMiddleware:
    """
    Two jobs:

    1. **Strip the ``/api`` prefix.** The SPA is hard-wired to ``baseURL: '/api'``
       (a leftover from the retired reverse-proxy setup). The backend does the
       rewriting itself, otherwise every request 404s.
    2. **Require a local token.** A loopback HTTP server is reachable by any
       process — and by any web page the user happens to have open — so an
       unauthenticated ``POST /api/chats/x`` would let a random site delete the
       library. The Tauri shell generates ``RAGVAULT_LOCAL_TOKEN`` and injects it
       into ``index.html``; the SPA echoes it back on every API call.

    The guard only covers the data namespaces. ``/health`` stays open so the
    shell can probe readiness before the window exists, and the SPA's own assets
    stay open because the browser fetches them before any JavaScript runs.
    """

    _GUARDED_PREFIXES = ("auth", "chats", "quiz", "notes", "settings", "config")

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path") or "/"
        is_api_call = path == "/api" or path.startswith("/api/")
        if is_api_call:
            rewritten = path[4:] or "/"
            scope = dict(scope)
            scope["path"] = rewritten
            scope["raw_path"] = rewritten.encode("latin-1")
            path = rewritten

        # Only API calls carry the token. The SPA's own routes (``/chats/<id>``,
        # ``/quiz``, …) are plain deep links the browser navigates to before any
        # JavaScript runs, so they must stay reachable without it.
        if LOCAL_TOKEN and is_api_call:
            first_segment = path.lstrip("/").split("/", 1)[0]
            exempt = path in _TOKEN_EXEMPT or first_segment not in self._GUARDED_PREFIXES
            if not exempt:
                supplied = ""
                for key, value in scope.get("headers") or []:
                    if key == LOCAL_TOKEN_HEADER:
                        supplied = value.decode("latin-1")
                        break
                if supplied != LOCAL_TOKEN:
                    await self._reject(send)
                    return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send) -> None:
        body = b'{"detail":"Invalid or missing local token."}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


app.add_middleware(DesktopLocalMiddleware)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(documents_router)
app.include_router(messages_router)
app.include_router(quiz_router)
app.include_router(notes_router)
app.include_router(settings_router)


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health() -> dict:
    """Liveness probe. The Tauri shell polls this until the backend is ready."""
    return {"status": "ok", "version": API_VERSION}


@app.get("/config", tags=["Health"])
async def client_config() -> dict:
    """
    Expose the non-secret runtime configuration the SPA needs.

    The frontend fetches this on boot so ``APP_LANGUAGE`` really drives the
    first paint, before any user preference is stored.
    """
    return {
        "default_language": i18n.configured_language(),
        "supported_languages": list(i18n.SUPPORTED_LANGUAGES),
        "active_language": i18n.current_language(),
        "audio_video_enabled": get_settings().enable_audio_video_uploads,
        "ocr_enabled": get_settings().enable_ocr_uploads,
        "version": API_VERSION,
    }


# ─── Static SPA ───────────────────────────────────────────────────────────────
# Registered last so it never shadows a real route. A no-op unless WEB_DIST_DIR
# points at a build (the desktop launcher always sets it).
mount_spa(app, get_settings().web_dist_dir, token=LOCAL_TOKEN or None)
