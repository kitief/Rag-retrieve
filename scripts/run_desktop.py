"""
Run RagVault as a single desktop-style process (development entry point).

This is the M0 deliverable described in ``docs/desktop-packaging.md``: no Docker,
no Postgres container, no Chroma container, no nginx. One Python process serves
the API *and* the built SPA on a loopback port, with SQLite and an embedded
Chroma store under a single data directory.

Usage::

    python scripts/run_desktop.py                     # http://127.0.0.1:<random>
    python scripts/run_desktop.py --port 8123         # fixed port
    python scripts/run_desktop.py --data-dir ./tmp    # throw-away profile

The script prints exactly one machine-readable line once the socket is bound::

    RAGVAULT_READY port=54321

The Tauri shell greps stdout for that line instead of guessing a port with
bind-then-close (which is racy: another process can grab the port in between).

The actual boot logic lives in ``backend/app/desktop_boot.py`` so that the
PyInstaller entry point (``backend/desktop_entry.py``) can reuse it verbatim.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    from app.desktop_boot import main as boot_main

    return boot_main(argv if argv is not None else sys.argv[1:], backend_root=BACKEND_ROOT)


if __name__ == "__main__":
    # `app` lives under backend/, so make it importable before the first import.
    sys.path.insert(0, str(BACKEND_ROOT))
    raise SystemExit(main())
