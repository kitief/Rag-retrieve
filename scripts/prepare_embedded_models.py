"""
Pre-download the FastEmbed ONNX model into ``build/desktop/fastembed``.

The desktop installer ships the weights so the first launch works offline —
downloading a ~65 MB model the first time a user uploads a PDF is not a good
experience, and it silently fails on networks that block huggingface.co.

Run once before packaging:

    .venv-desktop/Scripts/python.exe scripts/prepare_embedded_models.py

Then ``backend/ragvault-backend.spec`` picks the directory up and
``app/desktop_boot.py`` points ``HF_HOME`` at the bundled copy with
``HF_HUB_OFFLINE=1``.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "build" / "desktop" / "fastembed"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate the bundled FastEmbed model cache.")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="Destination cache directory.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="FastEmbed model name.")
    parser.add_argument(
        "--cache-dir",
        default="",
        help="Existing HF-style cache to copy from (e.g. .desktop-data/models).",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("RAGVAULT_HF_ENDPOINT", "https://hf-mirror.com"),
        help="HF mirror used when downloading.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    target = Path(args.target).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    if args.cache_dir:
        source = Path(args.cache_dir).expanduser().resolve()
        if not source.is_dir():
            print(f"[prepare] cache dir not found: {source}", file=sys.stderr)
            return 2
        copied = 0
        for entry in source.iterdir():
            if entry.name.startswith(("models--", "models")) and entry.is_dir():
                destination = target / entry.name
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(entry, destination)
                copied += 1
        print(f"[prepare] copied {copied} cache entries from {source}")

    os.environ["HF_HOME"] = str(target)
    os.environ.setdefault("HF_ENDPOINT", args.endpoint)
    # A copy-in must not phone home; a fresh download obviously must.
    if args.cache_dir:
        os.environ["HF_HUB_OFFLINE"] = "1"

    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=args.model, cache_dir=str(target))
    vector = next(iter(model.embed(["warm up"])))
    print(f"[prepare] model ready: {args.model} (dim={len(vector)})")

    onnx_files = sorted(target.rglob("*.onnx"))
    total = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
    print(f"[prepare] {len(onnx_files)} onnx file(s), {total / 1_048_576:.1f} MiB in {target}")
    for item in onnx_files:
        print(f"[prepare]   {item.relative_to(target)}")
    if not onnx_files:
        print("[prepare] ERROR: no .onnx weights found — the bundle would need the network.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
