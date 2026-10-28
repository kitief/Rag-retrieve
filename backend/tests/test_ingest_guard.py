"""
Guards around ingestion outcomes that used to be silent.

The complaint that started the layered PDF work was "I uploaded a scanned book
and it says it cannot find anything". Two failure modes made that invisible:

* a scan with OCR switched off parsed to zero pages and was still marked
  ``processed``, so the UI showed a green "ready" badge over an empty index;
* a failure left ``status='failed'`` with no reason, so the user could not tell
  a corrupt file from a configuration problem.
"""
from __future__ import annotations

import pytest

from app.services import ingestion_service as ing


def _audit(**overrides):
    base = {
        "filename": "book.pdf",
        "total_pages": 3,
        "digital_pages": 0,
        "scanned_pages": 3,
        "hybrid_pages": 0,
        "blank_pages": 0,
        "ocr_pages": 0,
        "ocr_failed_pages": 0,
        "ocr_skipped_pages": 0,
        "ocr_truncated": False,
        "ocr_engine": None,
        "ocr_available": True,
        "mean_confidence": 0.0,
        "low_confidence_pages": [],
        "text_chars": 0,
        "duration_seconds": 0.1,
        "warnings": [],
        "pages": [],
    }
    base.update(overrides)
    return base


def test_scan_with_ocr_engine_missing_is_an_error(monkeypatch):
    monkeypatch.setattr(
        ing, "parse_file_with_audit",
        lambda path, progress=None: ([], _audit(ocr_available=False)),
    )

    with pytest.raises(RuntimeError) as exc:
        ing._sync_ingest_pipeline("x.pdf", "book.pdf", "chat", "doc", 600, 100)

    assert "no OCR engine" in str(exc.value)


def test_scan_with_ocr_disabled_is_an_error(monkeypatch):
    monkeypatch.setattr(
        ing, "parse_file_with_audit",
        lambda path, progress=None: ([], _audit(ocr_skipped_pages=3)),
    )

    with pytest.raises(RuntimeError) as exc:
        ing._sync_ingest_pipeline("x.pdf", "book.pdf", "chat", "doc", 600, 100)

    assert "ENABLE_OCR_UPLOADS" in str(exc.value)


def test_partially_readable_scan_is_still_refused(monkeypatch):
    """
    The real complaint: 5 of 7 pages were scans and OCR was off, so two pages of
    fragments got indexed and the document was labelled "ready".
    """
    pages = [{"text": "碎片", "page": 6, "source": "tmp"}, {"text": "碎片", "page": 7, "source": "tmp"}]
    audit = _audit(total_pages=7, scanned_pages=5, ocr_skipped_pages=5)
    monkeypatch.setattr(ing, "parse_file_with_audit", lambda path, progress=None: (pages, audit))

    with pytest.raises(RuntimeError) as exc:
        ing._sync_ingest_pipeline("x.pdf", "book.pdf", "chat", "doc", 600, 100)

    assert "5 of 7" in str(exc.value)


def test_one_scanned_appendix_in_a_long_document_is_tolerated(monkeypatch):
    """A couple of unread pages in a 200-page report must not block the upload."""
    pages = [{"text": "body text", "page": 1, "source": "tmp"}]
    audit = _audit(total_pages=200, scanned_pages=2, digital_pages=198, ocr_skipped_pages=2)
    monkeypatch.setattr(ing, "parse_file_with_audit", lambda path, progress=None: (pages, audit))
    monkeypatch.setattr(ing, "embed_texts", lambda texts, **kwargs: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(ing, "add_chunks_to_collection", lambda *args, **kwargs: None)

    stats = ing._sync_ingest_pipeline("x.pdf", "report.pdf", "chat", "doc", 600, 100)

    assert stats["total_pages"] == 1
    assert stats["audit"]["ocr_skipped_pages"] == 2


def test_successfully_ocrd_scan_is_accepted(monkeypatch):
    pages = [{"text": "recognised text", "page": 1, "source": "tmp"}]
    audit = _audit(total_pages=3, scanned_pages=3, ocr_pages=3)
    monkeypatch.setattr(ing, "parse_file_with_audit", lambda path, progress=None: (pages, audit))
    monkeypatch.setattr(ing, "embed_texts", lambda texts, **kwargs: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(ing, "add_chunks_to_collection", lambda *args, **kwargs: None)

    stats = ing._sync_ingest_pipeline("x.pdf", "book.pdf", "chat", "doc", 600, 100)

    assert stats["audit"]["ocr_pages"] == 3


def test_blank_pdf_is_not_treated_as_a_scan_failure(monkeypatch):
    """A PDF of truly blank pages has nothing to OCR; it must not be an error."""
    monkeypatch.setattr(
        ing, "parse_file_with_audit",
        lambda path, progress=None: ([], _audit(scanned_pages=0, blank_pages=3)),
    )

    stats = ing._sync_ingest_pipeline("x.pdf", "book.pdf", "chat", "doc", 600, 100)

    assert stats["total_pages"] == 0
    assert stats["total_chunks"] == 0


def test_audit_filename_is_replaced_with_the_real_one(monkeypatch):
    """The audit is built from a UUID temp file; the dialog must show the name."""
    monkeypatch.setattr(
        ing, "parse_file_with_audit",
        lambda path, progress=None: (
            [{"text": "hello", "page": 1, "source": "tmp"}],
            _audit(scanned_pages=0, digital_pages=3),
        ),
    )
    # Embedding would download a model on a machine without the cache; these
    # tests care about the audit, not about vectors.
    monkeypatch.setattr(ing, "embed_texts", lambda texts, **kwargs: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(ing, "add_chunks_to_collection", lambda *args, **kwargs: None)

    stats = ing._sync_ingest_pipeline("x.pdf", "real name.pdf", "chat", "doc", 600, 100)

    assert stats["audit"]["filename"] == "real name.pdf"


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("This PDF is a scan and OCR did not run."), "This PDF is a scan and OCR did not run."),
        (ValueError("Unsupported file type: .xyz"), "Unsupported file type: .xyz"),
        (Exception(""), "Ingestion failed."),
        (OSError("disk full"), "Ingestion failed: disk full"),
    ],
)
def test_failure_reason_is_user_facing(exc, expected):
    assert ing._failure_reason(exc) == expected


def test_failure_reason_truncates_giant_messages():
    reason = ing._failure_reason(RuntimeError("x" * 5000))

    assert len(reason) == 500
