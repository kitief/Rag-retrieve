"""
Frozen (PyInstaller) entry point for the RagVault backend.

This is what ``ragvault-backend.exe`` actually runs. It only delegates to
``app.desktop_boot``; everything interesting (path resolution for
``sys._MEIPASS``, data-dir defaults, the ``RAGVAULT_READY port=…`` handshake)
lives there so the development launcher and the frozen binary cannot drift.

The Tauri shell spawns this with::

    ragvault-backend.exe --data-dir <app_data_dir> --port 0
"""
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path() -> None:
    """Make ``app`` importable in both frozen and source layouts."""
    if getattr(sys, "frozen", False):
        # onedir build: the package tree sits next to the executable / _internal.
        candidates = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
    else:
        candidates = [Path(__file__).resolve().parent]
    for candidate in candidates:
        if candidate and (candidate / "app").is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break


def main() -> int:
    _bootstrap_path()
    from app.desktop_boot import main as boot_main

    return boot_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
