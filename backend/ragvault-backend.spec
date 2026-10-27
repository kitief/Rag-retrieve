# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RagVault desktop backend (M1).

Build (from the repository root, with the desktop venv):

    .venv-desktop/Scripts/pyinstaller.exe backend/ragvault-backend.spec --noconfirm

Output: ``dist/ragvault-backend/ragvault-backend.exe`` (onedir — *not* onefile:
onefile re-extracts to %TEMP% on every launch, which is slow and trips AV
heuristics far more often).

The frozen app bundles three kinds of data that PyInstaller cannot infer:

* ``frontend/dist``      — the built SPA, served by ``app/core/spa.py``
* ``build/desktop/fastembed`` — pre-downloaded ONNX embedding model, so the
  first launch never touches the network (``HF_HUB_OFFLINE=1`` is then set by
  ``app/desktop_boot.py``)
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()          # backend/
REPO_ROOT = SPEC_DIR.parent                  # repository root

# Diagnostics: `RAGVAULT_ENTRY=backend/desktop_diag.py pyinstaller …` builds the
# same bundle around a different entry point, which is how the "frozen binary
# dies without a single line of output" class of bug gets bisected.
_entry_env = os.environ.get("RAGVAULT_ENTRY", "").strip()
ENTRY_SCRIPT = Path(_entry_env).resolve() if _entry_env else (SPEC_DIR / "desktop_entry.py")
APP_NAME = os.environ.get("RAGVAULT_APP_NAME", "").strip() or "ragvault-backend"

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
EMBEDDED_MODELS = REPO_ROOT / "build" / "desktop" / "fastembed"

if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        "frontend/dist is missing — run `npm run build` in frontend/ before packaging.\n"
        f"Looked for: {FRONTEND_DIST / 'index.html'}"
    )

if not EMBEDDED_MODELS.is_dir():
    raise SystemExit(
        "build/desktop/fastembed is missing — run `python scripts/prepare_embedded_models.py` "
        "once before packaging so the app ships with the embedding model.\n"
        f"Looked for: {EMBEDDED_MODELS}"
    )

datas = []
binaries = []
hiddenimports = []


def _merge(source: str) -> None:
    """collect_all() returns (datas, binaries, hiddenimports)."""
    d, b, h = collect_all(source)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Native / dynamic-loading packages: their submodules and shared libraries are
# invisible to static analysis.
for package in ("chromadb", "onnxruntime", "fastembed", "tokenizers", "huggingface_hub"):
    _merge(package)

# PyMuPDF ships a compiled extension and its own fonts.
_merge("fitz")
_merge("pymupdf")

# Async SQLite driver, loaded by SQLAlchemy through an URL string.
hiddenimports += collect_submodules("aiosqlite")
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")
hiddenimports += ["aiosqlite", "sqlalchemy.dialects.sqlite.aiosqlite"]

# uvicorn picks its protocol implementation by name at runtime.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# tiktoken bundles a Rust extension and reads its BPE files from package data.
# The encoding table itself lives in the separate ``tiktoken_ext`` namespace
# package, which PyInstaller cannot see statically — without it the frozen app
# dies with "Unknown encoding cl100k_base" and silently falls back to the
# approximate token counter.
datas += collect_data_files("tiktoken")
hiddenimports += collect_submodules("tiktoken")
datas += collect_data_files("tiktoken_ext")
hiddenimports += collect_submodules("tiktoken_ext")

# Alembic is only used by the Docker entrypoint, but the import chain in
# app/main.py is shared; keep it importable in case it is referenced.
hiddenimports += collect_submodules("alembic")

# --- bundled application data -------------------------------------------------
datas.append((str(FRONTEND_DIST), "frontend/dist"))
datas.append((str(EMBEDDED_MODELS), "fastembed"))

# The exception classes that FastAPI/Starlette resolve by dotted path.
hiddenimports += [
    "app.main",
    "app.desktop_boot",
    "app.routers.auth",
    "app.routers.chats",
    "app.routers.documents",
    "app.routers.messages",
    "app.routers.notes",
    "app.routers.quiz",
    "app.routers.settings",
    "app.services.llm_client",
    "app.services.rag_service",
    "app.services.quiz_service",
    "app.services.notes_service",
    "app.services.recommendation_service",
    "app.services.ingestion_service",
    "app.core.i18n",
    "app.core.spa",
]

block_cipher = None

a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(SPEC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Shrink the bundle: none of these are used by the desktop build and
        # several drag in heavyweight optional dependencies.
        "tkinter",
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "PyQt5",
        "PySide2",
        "torch",
        "tensorflow",
        "pandas",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


# --- VC++ runtime sanity -------------------------------------------------------
# PyInstaller picks up ``msvcp140.dll`` / ``vcruntime140*.dll`` from whichever
# package happens to ship them (here: an old 14.31 copy pulled in by a
# dependency) and puts them first on the DLL search path. onnxruntime 1.31 links
# against a newer runtime and dies with an access violation on import — with no
# output at all, because the crash happens inside the C++ loader before Python
# can print a traceback. Drop the vendored copies and let the system ones win.
_VC_RUNTIME = {"msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
_system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

_kept = []
for _entry in a.binaries:
    if Path(_entry[0]).name.lower() not in _VC_RUNTIME:
        _kept.append(_entry)

_present = {Path(entry[0]).name.lower() for entry in _kept}
for _name in sorted(_VC_RUNTIME - _present):
    _candidate = _system32 / _name
    if _candidate.is_file():
        _kept.append((_name, str(_candidate), "BINARY"))

a.binaries = _kept
_bundled_vc = sorted(
    Path(entry[0]).name for entry in a.binaries if Path(entry[0]).name.lower() in _VC_RUNTIME
)
print(f"[spec] VC runtime DLLs bundled: {_bundled_vc}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX breaks onnxruntime DLLs and trips AV scanners
    console=True,       # the shell parses stdout for RAGVAULT_READY
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
