"""
FastEmbed (ONNX Runtime) embedding wrapper.
Loads BAAI/bge-small-en-v1.5 (or configured model) as a singleton
and provides high-speed batch + single-text embedding functions without PyTorch overhead.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

from fastembed import TextEmbedding

logger = logging.getLogger(__name__)


def _model_present(cache_dir: str) -> bool:
    """True when the HuggingFace cache already holds a downloaded model."""
    try:
        root = Path(cache_dir)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False
    if not root.is_dir():
        return False
    return any(entry.is_dir() and entry.name.startswith("models--") for entry in root.iterdir())


@lru_cache(maxsize=1)
def get_embedding_model() -> TextEmbedding:
    """
    Load and cache the FastEmbed ONNX embedding model.
    Called once at startup / first embed; subsequent calls return the cached instance.

    When the cache directory already contains a downloaded model (the desktop
    build ships one inside the installer) HuggingFace is put in offline mode, so
    a machine without connectivity never waits on a network probe that can only
    time out — and, more importantly, never silently downloads a *different*
    model than the one the installer was built with.
    """
    from app.config import get_settings

    cfg = get_settings()

    if _model_present(cfg.hf_home) and not os.environ.get("HF_HUB_OFFLINE"):
        os.environ["HF_HUB_OFFLINE"] = "1"
        logger.info("Embedding cache at %s is pre-populated — running in offline mode.", cfg.hf_home)

    logger.info("Loading FastEmbed embedding model: %s", cfg.embedding_model)
    model = TextEmbedding(
        model_name=cfg.embedding_model,
        cache_dir=cfg.hf_home,
    )
    logger.info("FastEmbed embedding model loaded successfully: %s", cfg.embedding_model)
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts using FastEmbed (ONNX Runtime).

    Args:
        texts: List of strings to embed.

    Returns:
        List of float vectors (L2-normalized cosine embeddings).
    """
    if not texts:
        return []

    model = get_embedding_model()
    # model.embed returns a generator of numpy ndarrays
    embeddings = list(model.embed(texts))
    return [vec.tolist() for vec in embeddings]


def embed_single(text: str) -> list[float]:
    """Embed a single string. Convenience wrapper around embed_texts."""
    return embed_texts([text])[0]
