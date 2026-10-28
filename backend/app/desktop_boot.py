"""
Shared boot logic for the single-process (desktop) deployment.

Used by two entry points:

``scripts/run_desktop.py``
    Development: runs straight from the repository with the venv Python.

``backend/desktop_entry.py``
    Frozen build: the same logic, but paths come from ``sys._MEIPASS`` because
    PyInstaller unpacks the bundle into a temp/`_internal` directory.

The module deliberately imports ``app.config`` / ``app.main`` *inside* functions:
``get_settings()`` is ``lru_cache``d and the SQLAlchemy engine is created at
import time, so every environment variable below must be in place first.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

#: Printed once the socket is bound. The Tauri shell parses exactly this line
#: instead of probing ports, which is racy (another process may grab the port
#: between our probe and our bind).
READY_PREFIX = "RAGVAULT_READY port="

APP_DIR_NAME = "RagVault"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_root() -> Path:
    """Root that holds bundled data (frontend build, embedding model)."""
    if _is_frozen():
        # onedir: <dist>/ragvault-backend/_internal ; onefile: <temp>/_MEIPASS
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    """Per-user writable data directory.

    Windows: ``%APPDATA%\\RagVault\\data``. The shell normally passes
    ``--data-dir`` explicitly (from ``app.path().app_data_dir()``) — this is the
    fallback for running the binary by hand.
    """
    override = os.environ.get("RAGVAULT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME / "data"


def _default_web_dist() -> Path:
    if _is_frozen():
        return _bundle_root() / "frontend" / "dist"
    return _bundle_root() / "frontend" / "dist"


def _default_embedded_models() -> Path:
    """Model cache shipped inside the bundle (read-only, pre-populated)."""
    return _bundle_root() / "fastembed"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ragvault-backend",
        description="Run RagVault as a single process (SQLite + embedded Chroma).",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_default_data_dir()),
        help="Root for the SQLite DB, Chroma store, uploads and model cache.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("RAGVAULT_PORT", "0")),
        help="TCP port; 0 lets the OS pick a free one (recommended).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("RAGVAULT_HOST", "127.0.0.1"),
        help="Bind address. Keep it on loopback unless you know why not.",
    )
    parser.add_argument(
        "--web-dist",
        default=str(_default_web_dist()),
        help="Directory containing the built SPA (index.html + assets).",
    )
    parser.add_argument(
        "--embedded-models",
        default=str(_default_embedded_models()),
        help="Read-only directory holding the pre-downloaded embedding model.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "info"),
        help="uvicorn/app log level.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Restart on file changes (development only, ignored when frozen).",
    )
    return parser.parse_args(argv)


def configure_environment(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.setdefault("LOG_LEVEL", args.log_level.upper())

    # A desktop profile must not inherit a developer `.env` sitting next to the
    # repository (an API key, a language override) — each install is its own
    # profile and its settings live in the settings dialog.
    os.environ.setdefault("RAGVAULT_ENV_FILE", "")

    web_dist = Path(args.web_dist).expanduser()
    if (web_dist / "index.html").is_file():
        os.environ["WEB_DIST_DIR"] = str(web_dist.resolve())
    else:
        print(
            f"[run_desktop] No SPA build at {web_dist} — serving the API only.\n"
            f"             Run `npm run build` in frontend/ to serve the UI from here.",
            file=sys.stderr,
            flush=True,
        )
        os.environ.pop("WEB_DIST_DIR", None)

    # Embedding model: prefer the read-only copy bundled with the app, then the
    # per-user cache (first run may download once), so an upgrade of the bundle
    # does not silently re-download into the user profile.
    bundled_models = Path(args.embedded_models).expanduser()
    user_models = data_dir / "models"
    if (bundled_models / "models").is_dir() or (bundled_models / "models--Qdrant--bge-small-en-v1.5-onnx-Q").is_dir():
        os.environ["HF_HOME"] = str(bundled_models.resolve())
        # Bundled weights are frozen at build time — never go to the network.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.setdefault("HF_HOME", str(user_models))
        # huggingface.co is unreachable or very slow from mainland China, so
        # without the mirror the first ingestion stalls and then fails.
        os.environ.setdefault(
            "HF_ENDPOINT",
            os.environ.get("RAGVAULT_HF_ENDPOINT", "https://hf-mirror.com"),
        )

    # Keep the tiktoken BPE table under the writable data directory (the bundled
    # model folder is read-only inside the installer) so it is not re-downloaded
    # on every cold start.
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(user_models / "tiktoken"))


def serve_with_reload(host: str, port: int, log_level: str, backend_root: Path) -> int:
    """Run uvicorn's autoreloader (development only, never in the frozen build).

    The reloader needs an import string rather than an app instance, and it
    re-imports ``app.main`` in a child process, so every environment variable
    set by :func:`configure_environment` must already be in place — it is,
    because the child inherits our environment.

    The port has to be fixed: the child binds the socket, so the parent cannot
    discover a port chosen by the OS, and a ``RAGVAULT_READY`` line with a wrong
    port is worse than none.
    """
    import uvicorn

    if not port:
        port = 8000
        print(
            "[run_desktop] --reload needs a fixed port; using 8000.",
            flush=True,
        )

    print(f"{READY_PREFIX}{port}", flush=True)
    print(f"[run_desktop] Open http://{host}:{port}/  (reload on file changes)", flush=True)

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            log_level=log_level.lower(),
            access_log=False,
            reload=True,
            # Watch the backend only: the frontend has its own vite dev server,
            # and `dist/` churn would restart the API on every build.
            reload_dirs=[str(backend_root)],
        )
    except KeyboardInterrupt:
        print("[run_desktop] interrupted", flush=True)
        return 130
    return 0


async def serve(app, host: str, port: int, log_level: str) -> None:
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)

    async def announce() -> None:
        while not server.started:
            await asyncio.sleep(0.05)
        bound_port = port
        for server_obj in getattr(server, "servers", []):
            for sock in getattr(server_obj, "sockets", []) or []:
                try:
                    bound_port = int(sock.getsockname()[1])
                except OSError:  # pragma: no cover - defensive
                    pass
        print(f"{READY_PREFIX}{bound_port}", flush=True)
        print(f"[run_desktop] Open http://{host}:{bound_port}/", flush=True)

    await asyncio.gather(server.serve(), announce())


def _force_utf8_stdio() -> None:
    """Make our own prints survive non-ASCII paths.

    When stdio is a pipe, Python picks the encoding from the locale (cp936 on a
    zh-CN Windows box). Anything we print — the data dir usually — would then be
    mangled or raise ``UnicodeEncodeError`` deep inside uvicorn. Reconfiguring
    once at boot makes the child emit UTF-8 regardless of the parent's console.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # A real console already renders whatever the user's code page can
            # show; only piped stdio needs pinning to UTF-8 (the shell that
            # reads us parses `RAGVAULT_READY port=` out of it).
            if stream.isatty():
                continue
        except (ValueError, OSError):  # pragma: no cover - detached stdio
            pass
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - unusual stdio objects
            pass


def main(argv: list[str] | None = None, backend_root: Path | None = None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    configure_environment(args)

    if backend_root is not None and str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.config import get_settings

    # Autoreload spawns its own process that imports ``app.main`` itself, so the
    # parent must not import it: that would open the SQLite database twice and
    # print the banner a second time.
    if args.reload and not _is_frozen():
        cfg = get_settings()
        watch_root = backend_root or Path(__file__).resolve().parents[1]
        return serve_with_reload(args.host, args.port, cfg.log_level, watch_root)

    from app.main import app  # noqa: WPS433 - import after env setup, by design

    cfg = get_settings()

    print("[run_desktop] RagVault desktop mode", flush=True)
    print(f"[run_desktop]   frozen   : {_is_frozen()}", flush=True)
    print(f"[run_desktop]   data dir : {cfg.data_dir}", flush=True)
    print(f"[run_desktop]   database : {cfg.database_url}", flush=True)
    print(f"[run_desktop]   chroma   : {cfg.chroma_persist_dir}", flush=True)
    print(f"[run_desktop]   models   : {cfg.hf_home}", flush=True)
    print(f"[run_desktop]   spa      : {cfg.web_dist_dir or '(none)'}", flush=True)

    try:
        asyncio.run(serve(app, args.host, args.port or 0, cfg.log_level))
    except KeyboardInterrupt:
        print("[run_desktop] interrupted", flush=True)
        return 130
    return 0
