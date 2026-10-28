"""
Tests for the ingestion progress registry and the document schema that exposes
it.

Both exist purely to make long OCR jobs legible in the UI, and both have a
failure mode that is silent rather than loud: a progress bar that goes backwards,
and an audit blob that cannot be decoded. Those are the two things pinned here.
"""
import json

import pytest

from app.schemas.document import DocumentResponse
from app.services import progress as registry


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    registry._REPORTERS.clear()


def test_progress_only_moves_forward():
    reporter = registry.start("doc-1")
    reporter.update(40, "ocr", "page 12/30")
    reporter.update(25, "audit", "stale callback")

    snap = reporter.snapshot()
    assert snap["progress"] == 40
    # The stage still updates: only the percentage is monotonic, because a
    # reclassification ("this page needs OCR after all") is legitimate news.
    assert snap["stage"] == "audit"


def test_progress_is_clamped_to_0_100():
    reporter = registry.start("doc-1")
    reporter.update(-10)
    assert reporter.snapshot()["progress"] == 0
    reporter.update(500)
    assert reporter.snapshot()["progress"] == 100


def test_registry_round_trip():
    reporter = registry.start("doc-2")
    reporter.update(55, "embed", "3/8")

    assert registry.get("doc-2") is reporter
    assert registry.snapshot("doc-2")["stage"] == "embed"

    registry.finish("doc-2")
    assert registry.get("doc-2") is None
    assert registry.snapshot("doc-2") is None


def test_start_resets_an_existing_reporter():
    first = registry.start("doc-3")
    first.update(90, "store")
    second = registry.start("doc-3")

    assert second is not first
    assert second.snapshot()["progress"] == 0


# ── Schema ───────────────────────────────────────────────────────────────────
_AUDIT = {
    "filename": "scan.pdf",
    "total_pages": 7,
    "ocr_pages": 5,
    "mean_confidence": 0.9873,
    "pages": [{"page": 1, "kind": "scanned", "ocr_used": True}],
}


def _document_payload(**overrides):
    base = {
        "id": "0b9d1a52-3c47-4a55-9a4e-4f0d4b4f1c11",
        "chat_id": "9a1c04a4-1f2b-4a9e-8f8e-2c3f0d3f7a22",
        "filename": "scan.pdf",
        "file_type": "pdf",
        "upload_time": "2026-10-28T12:00:00Z",
        "status": "processed",
    }
    base.update(overrides)
    return base


def test_parse_audit_json_text_is_decoded_to_a_dict():
    doc = DocumentResponse.model_validate(
        _document_payload(parse_audit=json.dumps(_AUDIT, ensure_ascii=False))
    )
    assert doc.parse_audit["ocr_pages"] == 5
    assert doc.parse_audit["pages"][0]["page"] == 1


def test_parse_audit_already_a_dict_passes_through():
    doc = DocumentResponse.model_validate(_document_payload(parse_audit=_AUDIT))
    assert doc.parse_audit["filename"] == "scan.pdf"


def test_corrupt_parse_audit_does_not_break_the_document():
    """One bad blob must not make the whole document list unrenderable."""
    doc = DocumentResponse.model_validate(_document_payload(parse_audit="{not json"))
    assert doc.parse_audit is None


@pytest.mark.parametrize("value", [None, "", "   ", "[]", "42", 12345])
def test_unusable_parse_audit_values_become_none(value):
    doc = DocumentResponse.model_validate(_document_payload(parse_audit=value))
    assert doc.parse_audit is None


def test_progress_fields_are_optional():
    doc = DocumentResponse.model_validate(_document_payload())
    assert doc.progress is None
    assert doc.progress_stage is None
    assert doc.parse_audit is None
