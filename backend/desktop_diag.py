"""Diagnostic entry point: import the frozen app in stages, printing progress."""
from __future__ import annotations

import os
import sys


def say(msg: str) -> None:
    print(f"[diag] {msg}", flush=True)


def main() -> int:
    say(f"frozen={getattr(sys, 'frozen', False)} meipass={getattr(sys, '_MEIPASS', '')}")
    target = sys.argv[sys.argv.index("--data-dir") + 1] if "--data-dir" in sys.argv else "diag-data"
    os.environ["DATA_DIR"] = os.path.abspath(target)
    os.environ["RAGVAULT_ENV_FILE"] = ""
    os.environ["HF_HOME"] = os.path.join(getattr(sys, "_MEIPASS", os.getcwd()), "fastembed")
    os.environ["HF_HUB_OFFLINE"] = "1"

    steps = [
        ("sqlalchemy", "import sqlalchemy"),
        ("aiosqlite", "import aiosqlite"),
        ("fastapi", "import fastapi"),
        ("pydantic", "import pydantic"),
        ("tiktoken", "import tiktoken"),
        ("pymupdf", "import pymupdf"),
        ("onnxruntime", "import onnxruntime"),
        ("fastembed", "import fastembed"),
        ("chromadb", "import chromadb"),
        ("app.config", "from app.config import get_settings"),
        ("app.database", "import app.database"),
        ("app.main", "from app.main import app"),
    ]
    for label, statement in steps:
        say(f"importing {label} …")
        try:
            exec(statement, {})
        except Exception as exc:  # noqa: BLE001
            say(f"FAILED {label}: {type(exc).__name__}: {exc}")
            return 1
        say(f"ok {label}")
    say("all imports ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
