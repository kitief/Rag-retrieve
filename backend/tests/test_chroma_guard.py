"""
Defensive behaviour around damaged ChromaDB records.

A killed process can leave a chunk with an embedding but no document text, or
text but no metadata. Chroma hands those back with ``None`` in the payload, and
``meta.get(...)`` then raises ``AttributeError`` deep inside retrieval -- which
surfaces to the client as a dropped connection rather than a useful error. These
tests pin down that such records are skipped instead.
"""
from __future__ import annotations

import pytest

from app.utils import chroma_client as cc


class _FakeCollection:
    """Minimal stand-in for ``chromadb.Collection``."""

    def __init__(self, ids, documents, metadatas, distances=None):
        self._ids = ids
        self._documents = documents
        self._metadatas = metadatas
        self._distances = distances if distances is not None else [0.1] * len(ids)
        self.deleted_ids: list[str] = []
        self.deleted_where = None

    def count(self) -> int:
        return len(self._ids)

    def query(self, query_embeddings, n_results, include=None):
        return {
            "ids": [list(self._ids)],
            "documents": [list(self._documents)],
            "metadatas": [list(self._metadatas)],
            "distances": [list(self._distances)],
        }

    def get(self, include=None, limit=None):
        return {
            "ids": list(self._ids),
            "documents": list(self._documents),
            "metadatas": list(self._metadatas),
        }

    def delete(self, ids=None, where=None):
        if ids is not None:
            self.deleted_ids.extend(ids)
        if where is not None:
            self.deleted_where = where


@pytest.fixture
def fake(monkeypatch):
    """Install a fake collection and return a setter for its contents."""

    def install(ids, documents, metadatas, distances=None):
        collection = _FakeCollection(ids, documents, metadatas, distances)
        monkeypatch.setattr(cc, "get_or_create_collection", lambda chat_id: collection)
        return collection

    return install


def test_query_skips_chunk_without_metadata(fake):
    """A record with no metadata must not raise; it is simply not a candidate."""
    fake(
        ids=["d1_0", "d1_1"],
        documents=["real text", "orphan text"],
        metadatas=[{"source": "a.pdf", "page": 1}, None],
    )
    hits = cc.query_collection("chat", [0.0] * 4, k=5, max_distance=None)

    assert len(hits) == 1
    assert hits[0]["text"] == "real text"
    assert hits[0]["source"] == "a.pdf"


def test_query_skips_chunk_without_text(fake):
    """A record with metadata but no text cannot be cited either."""
    fake(
        ids=["d1_0", "d1_1"],
        documents=["", "usable"],
        metadatas=[{"source": "a.pdf", "page": 1}, {"source": "a.pdf", "page": 2}],
    )
    hits = cc.query_collection("chat", [0.0] * 4, k=5, max_distance=None)

    assert [h["page"] for h in hits] == [2]


def test_query_prefers_distinct_documents(fake):
    """Two chunks of one document must not crowd out a second document."""
    fake(
        ids=["d1_0", "d1_1", "d2_0"],
        documents=["first", "second", "third"],
        metadatas=[
            {"source": "a.pdf", "page": 1, "document_id": "d1"},
            {"source": "a.pdf", "page": 2, "document_id": "d1"},
            {"source": "b.pdf", "page": 1, "document_id": "d2"},
        ],
        distances=[0.1, 0.2, 0.3],
    )
    hits = cc.query_collection("chat", [0.0] * 4, k=2, max_distance=None)

    assert [h["document_id"] for h in hits] == ["d1", "d2"]


def test_query_respects_max_distance(fake):
    fake(
        ids=["d1_0", "d1_1"],
        documents=["near", "far"],
        metadatas=[
            {"source": "a.pdf", "page": 1, "document_id": "d1"},
            {"source": "a.pdf", "page": 2, "document_id": "d1"},
        ],
        distances=[0.2, 0.9],
    )
    hits = cc.query_collection("chat", [0.0] * 4, k=5, max_distance=0.5)

    assert [h["text"] for h in hits] == ["near"]


def test_get_all_chunks_skips_damaged_records(fake):
    fake(
        ids=["d1_0", "d1_1", "d1_2"],
        documents=["good", None, "   "],
        metadatas=[{"source": "a.pdf"}, {"source": "a.pdf"}, {"source": "a.pdf"}],
    )
    hits = cc.get_all_chunks("chat")

    assert [h["text"] for h in hits] == ["good"]


def test_purge_broken_chunks_removes_only_damaged(fake):
    """The sweep must delete damaged ids and leave healthy neighbours alone."""
    collection = fake(
        ids=["d1_0", "d1_1", "d2_0"],
        documents=["good", None, "also good"],
        metadatas=[{"source": "a.pdf"}, {"source": "a.pdf"}, {"source": "b.pdf"}],
    )

    removed = cc.purge_broken_chunks("chat")

    assert removed == 1
    assert collection.deleted_ids == ["d1_1"]


def test_purge_broken_chunks_scoped_to_document(fake):
    """With a document id, damaged records of other documents stay put."""
    collection = fake(
        ids=["d1_0", "d2_0"],
        documents=[None, None],
        metadatas=[{"source": "a.pdf"}, {"source": "b.pdf"}],
    )

    removed = cc.purge_broken_chunks("chat", document_id="d2")

    assert removed == 1
    assert collection.deleted_ids == ["d2_0"]


def test_purge_broken_chunks_noop_on_healthy_collection(fake):
    collection = fake(
        ids=["d1_0"],
        documents=["fine"],
        metadatas=[{"source": "a.pdf"}],
    )

    assert cc.purge_broken_chunks("chat") == 0
    assert collection.deleted_ids == []


def test_delete_document_chunks_also_sweeps(fake):
    """Deleting a document must not leave orphaned id-only chunks behind."""
    collection = fake(
        ids=["d1_0", "d1_1"],
        documents=["good", None],
        metadatas=[{"source": "a.pdf"}, None],
    )

    cc.delete_document_chunks("chat", "d1")

    assert collection.deleted_where == {"document_id": {"$eq": "d1"}}
    assert collection.deleted_ids == ["d1_1"]
