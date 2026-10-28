"""
Serve the built SPA from the API process.

The desktop app has no separate web server: one Python process must answer both
the API and the UI, so the window loads ``http://127.0.0.1:PORT/`` and every
relative URL in the SPA (``baseURL: '/api'``, ``fetch('/api/...')``) keeps
working untouched.

The SPA is installed as an **ASGI middleware** rather than a catch-all route on
purpose: FastAPI matches routes in registration order, so a route for
``/chats/{chat_id}`` (the API handler) would shadow the SPA deep link
``/chats/<uuid>`` no matter when the catch-all is registered. Sitting outside
the router lets the middleware decide first — ``/api/*`` goes to FastAPI,
everything else is a page in the SPA.

Everything here is a no-op when ``WEB_DIST_DIR`` does not point at a real build,
so a backend-only run (``scripts/dev.ps1 -BackendOnly``, the test suite) still
works against the Vite dev server.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths that belong to the API/OpenAPI surface. Everything else is a page.
_API_EXACT = frozenset({"/health", "/config", "/docs", "/redoc", "/openapi.json"})
_API_PREFIXES = ("/api", "/docs/")

_TOKEN_META = '<meta name="ragvault-token" content="{token}">'


def is_api_path(path: str) -> bool:
    """True when ``path`` must be routed to FastAPI instead of the SPA."""
    if path in _API_EXACT:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _API_PREFIXES)


def resolve_dist(raw: str) -> Path | None:
    """Return the build directory when ``raw`` points at a real SPA build."""
    if not raw or not raw.strip():
        return None
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        # Relative paths are resolved against the backend/ directory, which is
        # what a developer means when typing ``--web-dist frontend/dist``.
        candidate = Path(__file__).resolve().parents[2] / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    return candidate if (candidate / "index.html").is_file() else None


class SpaMiddleware:
    """
    Answer non-API requests with files from the build, falling back to index.html.

    ``token`` is injected into ``index.html`` as a meta tag so the SPA can echo
    it back on every API call (see the local-token guard in :mod:`app.main`).
    """

    def __init__(self, app: ASGIApp, dist: Path, token: str | None = None) -> None:
        self.app = app
        self.dist = dist
        self.index_file = dist / "index.html"
        self.token = token
        self._cache: bytes | None = None
        self._cache_stamp: tuple[int, int] | None = None

    def _render_index(self) -> bytes:
        # Re-read whenever the build changes. Caching by identity alone would
        # keep serving the previous bundle after `npm run build` until the
        # process restarts, which makes a rebuilt UI look like it never shipped.
        try:
            stat = self.index_file.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if self._cache is not None and stamp is not None and stamp == self._cache_stamp:
            return self._cache
        html = self.index_file.read_text(encoding="utf-8")
        if self.token:
            meta = _TOKEN_META.format(token=self.token)
            if meta not in html:
                html = html.replace("</head>", f"    {meta}\n  </head>", 1)
        payload = html.encode("utf-8")
        self._cache = payload
        self._cache_stamp = stamp
        return payload

    def _resolve_file(self, path: str) -> Path | None:
        relative = path.lstrip("/")
        if not relative:
            return None
        candidate = (self.dist / relative).resolve()
        try:
            inside = candidate.is_relative_to(self.dist)
        except ValueError:  # pragma: no cover - different drive on Windows
            return None
        return candidate if inside and candidate.is_file() else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path") or "/"
        if is_api_path(path) or scope.get("method") not in (None, "GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        target = self._resolve_file(path)
        if target is not None:
            media_type, _ = mimetypes.guess_type(target.name)
            response = FileResponse(target, media_type=media_type)
        else:
            response = Response(
                content=self._render_index(),
                media_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        await response(scope, receive, send)


def mount_spa(app: FastAPI, raw_dir: str, token: str | None = None) -> bool:
    """
    Serve the built SPA from ``app`` as an outermost ASGI middleware.

    Returns True when a build was found and mounted.
    """
    dist = resolve_dist(raw_dir)
    if dist is None:
        logger.info(
            "SPA build not found at %r — API-only mode (run `npm run build` in frontend/).",
            raw_dir,
        )
        return False

    app.add_middleware(SpaMiddleware, dist=dist, token=token)
    logger.info("Serving SPA from %s", dist)
    return True
