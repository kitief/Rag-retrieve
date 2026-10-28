"""
ChromaDB client wrapper.
Provides collection management, chunk storage, querying, and deletion.

Vectors live in an embedded ``PersistentClient`` under ``chroma_persist_dir``
(``<data-dir>/chroma``). There is no Chroma server to probe: the whole product
is one process, so a heartbeat check could only ever fail and would cost 1-2s
of startup.
"""
import logging
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.ClientAPI:
    """Return the embedded ChromaDB client for the active data directory."""
    from app.config import get_settings

    cfg = get_settings()
    logger.info("Using embedded ChromaDB PersistentClient at %s", cfg.chroma_persist_dir)
    return chromadb.PersistentClient(
        path=cfg.chroma_persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )


def _collection_name(chat_id: str) -> str:
    """Derive a valid ChromaDB collection name from a chat UUID."""
    # ChromaDB collection names must match [a-zA-Z0-9_-]{3,63}
    return f"chat_{chat_id.replace('-', '_')}"


def get_or_create_collection(chat_id: str) -> chromadb.Collection:
    """Return (or create) the ChromaDB collection for a given chat_id."""
    client = get_chroma_client()
    name = _collection_name(chat_id)
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
    logger.debug("Using collection: %s", name)
    return collection


def add_chunks_to_collection(
    chat_id: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
    document_id: str,
) -> None:
    """
    Upsert document chunks into the chat's ChromaDB collection.
    Accumulates knowledge — does NOT replace existing chunks.

    Args:
        chat_id:     The UUID of the chat (knowledge space).
        chunks:      List of dicts with keys: text, page, source, chunk_index.
        embeddings:  Parallel list of embedding vectors.
        document_id: UUID of the parent document (used for per-doc deletion).
    """
    collection = get_or_create_collection(chat_id)

    ids = [f"{document_id}_{chunk['chunk_index']}" for chunk in chunks]
    metadatas: list[dict[str, Any]] = [
        {
            "chat_id": chat_id,
            "document_id": document_id,
            "source": chunk["source"],
            "page": int(chunk["page"]),
            "chunk_index": int(chunk["chunk_index"]),
        }
        for chunk in chunks
    ]
    documents = [chunk["text"] for chunk in chunks]

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents,
    )
    logger.info(
        "Upserted %d chunks into collection %s (document_id=%s)",
        len(chunks),
        _collection_name(chat_id),
        document_id,
    )


def query_collection(
    chat_id: str,
    query_embedding: list[float],
    k: int = 5,
    max_distance: float | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve the top-k most similar chunks for a query embedding.
    Optionally filter out chunks exceeding max_distance threshold.

    Returns:
        List of dicts: {text, source, page, chunk_index, document_id, distance}
    """
    collection = get_or_create_collection(chat_id)

    try:
        count = collection.count()
        if count == 0:
            return []
        effective_k = min(max(k * 3, k), count)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("ChromaDB query failed: %s", exc)
        return []

    docs = results.get("documents", [[]])[0] or []
    metas = results.get("metadatas", [[]])[0] or []
    dists = results.get("distances", [[]])[0] or []

    candidates: list[dict[str, Any]] = []
    for doc_text, meta, dist in zip(docs, metas, dists):
        # A half-written record (process killed mid-upsert) comes back with
        # ``None`` where its text or metadata should be. Such a chunk cannot be
        # cited, so it is dropped here -- the alternative is a 500 deep inside
        # retrieval, which reaches the user as a dropped connection.
        if meta is None or doc_text is None or not doc_text.strip():
            continue
        dist_val = float(dist)
        item = {
            "text": doc_text,
            "source": meta.get("source", "unknown"),
            "page": meta.get("page", 0),
            "chunk_index": meta.get("chunk_index", 0),
            "document_id": meta.get("document_id", ""),
            "distance": dist_val,
        }
        if max_distance is None or dist_val <= max_distance:
            candidates.append(item)

    if not candidates:
        logger.info("No chunks met max_distance threshold (%.2f) for chat %s", max_distance or 0.0, chat_id)
        return []

    # Prefer relevant chunks from different uploaded documents before filling
    # the remaining slots with the strongest matches.
    hits: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for candidate in candidates:
        document_id = candidate["document_id"] or candidate["source"]
        if document_id not in selected_ids:
            hits.append(candidate)
            selected_ids.add(document_id)
        if len(hits) == k:
            return hits

    for candidate in candidates:
        if candidate not in hits:
            hits.append(candidate)
        if len(hits) == k:
            break

    return hits


def delete_collection(chat_id: str) -> None:
    """Delete the entire ChromaDB collection for a chat (clear knowledge)."""
    client = get_chroma_client()
    name = _collection_name(chat_id)
    try:
        client.delete_collection(name)
        logger.info("Deleted ChromaDB collection: %s", name)
    except Exception as exc:
        logger.warning("Collection %s not found or already deleted: %s", name, exc)


def delete_document_chunks(chat_id: str, document_id: str) -> None:
    """Remove all chunks belonging to a specific document from the collection."""
    collection = get_or_create_collection(chat_id)
    try:
        collection.delete(where={"document_id": {"$eq": document_id}})
        logger.info(
            "Deleted chunks for document_id=%s from collection %s",
            document_id,
            _collection_name(chat_id),
        )
    except Exception as exc:
        logger.warning("Failed to delete chunks for document %s: %s", document_id, exc)
    # A chunk whose metadata never landed cannot be matched by the filter above,
    # yet its id still starts with the document id. Sweep those by id.
    purge_broken_chunks(chat_id, document_id=document_id)


def purge_broken_chunks(chat_id: str, document_id: str | None = None) -> int:
    """
    Delete chunks that carry no text or no metadata, and return how many went.

    An interrupted upsert (process killed mid-write) can leave a record with an
    embedding but no document text, or text but no metadata. Such a record is
    invisible to retrieval (we skip it) but still inflates ``count()``, and it is
    unreachable by the ``document_id`` filter used for deletion because that
    filter reads the very metadata that is missing. Removing it by id is the
    only way to get the collection back to a truthful size.
    """
    collection = get_or_create_collection(chat_id)
    try:
        got = collection.get(include=["documents", "metadatas"])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not inspect collection %s: %s", _collection_name(chat_id), exc)
        return 0

    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    docs = got.get("documents") or []

    dead: list[str] = []
    for chunk_id, meta, doc_text in zip(ids, metas, docs):
        broken = meta is None or doc_text is None or not str(doc_text).strip()
        if not broken:
            continue
        if document_id and not str(chunk_id).startswith(f"{document_id}_"):
            continue
        dead.append(chunk_id)

    if not dead:
        return 0

    try:
        collection.delete(ids=dead)
        logger.warning(
            "Purged %d broken chunk(s) from collection %s%s",
            len(dead),
            _collection_name(chat_id),
            f" (document_id={document_id})" if document_id else "",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to purge broken chunks from %s: %s", _collection_name(chat_id), exc)
        return 0
    return len(dead)


def get_all_chunks(chat_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve chunks from the chat's collection without query embeddings."""
    collection = get_or_create_collection(chat_id)
    try:
        results = collection.get(
            limit=limit,
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        logger.warning("ChromaDB get failed: %s", exc)
        return []

    hits: list[dict[str, Any]] = []
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []

    for doc_text, meta in zip(docs, metas):
        # A chunk without metadata or text cannot be cited; skip it rather than
        # letting ``meta.get`` raise on a None returned by Chroma.
        meta = meta or {}
        if doc_text is None or not doc_text.strip():
            continue
        hits.append(
            {
                "text": doc_text,
                "source": meta.get("source", "unknown"),
                "page": meta.get("page", 0),
                "chunk_index": meta.get("chunk_index", 0),
                "document_id": meta.get("document_id", ""),
            }
        )
    return hits
