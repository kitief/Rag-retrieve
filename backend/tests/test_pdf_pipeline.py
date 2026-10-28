"""
Tests for the layered PDF pipeline (``app/utils/pdf_pipeline.py``).

The pipeline's job is to decide, *before* spending any OCR time, which pages can
be trusted as-is and which ones need reading as pixels. Those decisions are pure
functions of the text layer and the image geometry, so they can be tested with
tiny generated PDFs and no OCR engine at all. A fake engine stands in for
RapidOCR where the test needs to prove that OCR output actually replaces a
broken text layer.
"""
import io

import fitz
import pytest

from app.utils import pdf_pipeline as pp


# ── Helpers ──────────────────────────────────────────────────────────────────
def _png_bytes(size=(600, 800), colour=200) -> bytes:
    """A blank PNG, used as the page-sized image of a simulated scan."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, (colour, colour, colour)).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_pdf(path, pages):
    """
    Build a PDF from a list of page specs.

    Each spec is a dict with optional ``text`` (drawn as a real text layer) and
    ``image`` (a full-page raster), which is exactly the pair of signals the
    audit looks at.
    """
    doc = fitz.open()
    for spec in pages:
        page = doc.new_page(width=595, height=842)  # A4 at 72 dpi
        if spec.get("image"):
            page.insert_image(page.rect, stream=_png_bytes())
        if spec.get("text"):
            page.insert_textbox(
                fitz.Rect(50, 50, 545, 792),
                spec["text"],
                fontsize=11,
                fontname="helv",
            )
    doc.save(str(path))
    doc.close()
    return str(path)


_LONG = "The quarterly report covers revenue, headcount and churn. " * 12


# ── text_quality ─────────────────────────────────────────────────────────────
def test_empty_text_scores_zero():
    assert pp.text_quality("") == 0.0
    assert pp.text_quality("   \n\n ") == 0.0


def test_real_prose_scores_high():
    assert pp.text_quality(_LONG) > 0.8


def test_glyph_soup_scores_low():
    """A handful of characters over a page is the signature of a bad OCR layer."""
    assert pp.text_quality("武 装 斗\n争 实\n现") < pp.QUALITY_FLOOR


def test_replacement_characters_are_penalised():
    clean = pp.text_quality(_LONG)
    dirty = pp.text_quality(_LONG.replace("revenue", "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd"))
    assert dirty < clean


# ── audit_page ───────────────────────────────────────────────────────────────
def test_digital_page_is_classified_as_digital(tmp_path):
    path = _make_pdf(tmp_path / "digital.pdf", [{"text": _LONG}])
    doc = fitz.open(path)
    try:
        audit, _raw = pp.audit_page(doc.load_page(0), 1, fitz)
    finally:
        doc.close()
    assert audit.kind == pp.KIND_DIGITAL
    assert audit.needs_ocr is False
    assert audit.chars > 500


def test_scanned_page_needs_ocr(tmp_path):
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    doc = fitz.open(path)
    try:
        audit, _raw = pp.audit_page(doc.load_page(0), 1, fitz)
    finally:
        doc.close()
    assert audit.kind == pp.KIND_SCANNED
    assert audit.needs_ocr is True
    assert audit.image_coverage >= 0.5


def test_fragment_text_layer_over_a_scan_needs_ocr(tmp_path):
    """
    The 毛泽东选集 failure mode: an image page carrying a few stray glyphs.

    Trusting that layer is exactly how a page ends up contributing six
    characters to the index while the model claims the document is empty.
    """
    path = _make_pdf(tmp_path / "fragment.pdf", [{"image": True, "text": "武 装 斗\n争"}])
    doc = fitz.open(path)
    try:
        audit, _raw = pp.audit_page(doc.load_page(0), 1, fitz)
    finally:
        doc.close()
    assert audit.kind == pp.KIND_SCANNED
    assert audit.needs_ocr is True
    assert "full-page image" in audit.note


def test_blank_page_is_not_sent_to_ocr(tmp_path):
    path = _make_pdf(tmp_path / "blank.pdf", [{}])
    doc = fitz.open(path)
    try:
        audit, _raw = pp.audit_page(doc.load_page(0), 1, fitz)
    finally:
        doc.close()
    assert audit.kind == pp.KIND_BLANK
    assert audit.needs_ocr is False


def test_page_sized_image_with_good_text_layer_keeps_the_text_layer(tmp_path):
    """A real text layer over a background image is exact; OCR could only lose it."""
    path = _make_pdf(tmp_path / "hybrid.pdf", [{"image": True, "text": _LONG}])
    doc = fitz.open(path)
    try:
        audit, _raw = pp.audit_page(doc.load_page(0), 1, fitz)
    finally:
        doc.close()
    assert audit.kind == pp.KIND_HYBRID
    assert audit.needs_ocr is False


# ── Reflow and reading order ─────────────────────────────────────────────────
def test_cjk_lines_are_joined_until_terminal_punctuation():
    text = pp.reflow_ocr_text("第一句话还没\n说完就换行了。\n第二句话。")
    assert text.split("\n")[0] == "第一句话还没说完就换行了。"
    assert len(text.split("\n")) == 2


def test_latin_lines_are_unwrapped_and_hyphens_rejoined():
    text = pp.reflow_ocr_text("This sentence was hard-\nwrapped in the middle.\nShort")
    assert "hardwrapped" in text.replace(" ", "")
    assert "\n" not in text.split("Short")[0].strip()


def test_blocks_are_ordered_left_to_right_within_a_band():
    blocks = [
        pp.OcrBlock("B", (200.0, 10.0, 300.0, 30.0), 0.9),
        pp.OcrBlock("A", (10.0, 10.0, 100.0, 30.0), 0.9),
        pp.OcrBlock("C", (10.0, 100.0, 100.0, 120.0), 0.9),
    ]
    assert pp._blocks_to_text(blocks) == "A B\nC"


# ── Serialisation ────────────────────────────────────────────────────────────
def test_audit_serialises_to_json_safe_primitives(tmp_path):
    import json

    path = _make_pdf(tmp_path / "mixed.pdf", [{"text": _LONG}, {"image": True}, {}])
    doc = fitz.open(path)
    try:
        audits = [pp.audit_page(doc.load_page(i), i + 1, fitz)[0] for i in range(3)]
    finally:
        doc.close()

    report = pp.PdfAudit(filename="mixed.pdf", total_pages=3)
    report.digital_pages = 1
    report.scanned_pages = 1
    report.blank_pages = 1
    report.pages = audits
    report.text_chars = sum(a.chars for a in audits)

    data = report.to_dict(page_mode="all")
    json.dumps(data)  # must not raise
    assert len(data["pages"]) == 3
    assert data["pages"][0]["kind"] == pp.KIND_DIGITAL


def test_notable_page_mode_drops_boring_pages():
    report = pp.PdfAudit(filename="x.pdf", total_pages=2)
    plain = pp.PageAudit(page=1, kind=pp.KIND_DIGITAL, chars=900)
    scanned = pp.PageAudit(page=2, kind=pp.KIND_SCANNED, needs_ocr=True)
    report.pages = [plain, scanned]

    assert [p["page"] for p in report.to_dict()["pages"]] == [2]
    assert [p["page"] for p in report.to_dict(page_mode="all")["pages"]] == [1, 2]
    assert report.to_dict(page_mode="none")["pages"] == []


def test_a_notable_audit_stays_small_for_a_long_book():
    """A 1400-page book must not persist 1400 records; aggregates carry that."""
    report = pp.PdfAudit(filename="book.pdf", total_pages=1400)
    report.pages = [
        pp.PageAudit(page=i, kind=pp.KIND_DIGITAL, chars=1200) for i in range(1, 1401)
    ]
    import json

    payload = json.dumps(report.to_dict())
    assert report.to_dict()["pages"] == []
    assert len(payload) < 1000


# ── End-to-end with a fake engine ────────────────────────────────────────────
class _FakeEngine(pp.OcrEngine):
    """Stands in for RapidOCR: returns fixed text, so OCR plumbing is testable."""

    name = "fake"

    def __init__(self, text="这台机器负责生产线的日常巡检工作。", confidence=0.95):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def run(self, image_bytes):
        self.calls += 1
        return [pp.OcrBlock(self.text, (10.0, 10.0, 400.0, 40.0), self.confidence)]


@pytest.fixture()
def fake_engine(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(pp, "load_ocr_engine", lambda preferred="auto", **kw: engine)
    return engine


def test_scan_is_ocrd_and_replaces_the_text_layer(tmp_path, fake_engine):
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    pages, audit = pp.parse_pdf_document(path)

    assert fake_engine.calls == 1
    assert audit["ocr_pages"] == 1
    assert audit["scanned_pages"] == 1
    assert pages[0]["page"] == 1
    assert "生产线" in pages[0]["text"]
    assert audit["pages"][0]["text_source"] == "ocr"
    assert audit["pages"][0]["ocr_confidence"] == pytest.approx(0.95, abs=1e-3)


def test_digital_pdf_is_never_sent_to_ocr(tmp_path, fake_engine):
    path = _make_pdf(tmp_path / "digital.pdf", [{"text": _LONG}, {"text": _LONG}])
    pages, audit = pp.parse_pdf_document(path)

    assert fake_engine.calls == 0
    assert audit["ocr_pages"] == 0
    assert audit["digital_pages"] == 2
    assert len(pages) == 2


def test_ocr_disabled_reports_the_pages_it_could_not_read(tmp_path):
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}, {"image": True}])
    pages, audit = pp.parse_pdf_document(path, ocr_enabled=False)

    assert pages == []
    assert audit["ocr_skipped_pages"] == 2
    assert any("need OCR but OCR is disabled" in w for w in audit["warnings"])
    # "OCR was switched off" is a different problem from "no engine installed",
    # and the caller needs to tell them apart to give the right advice.
    assert audit["ocr_available"] is True


def test_missing_engine_is_reported_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "load_ocr_engine", lambda preferred="auto", **kw: None)
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])

    pages, audit = pp.parse_pdf_document(path)

    assert pages == []
    assert audit["ocr_skipped_pages"] == 1
    assert audit["ocr_available"] is False
    assert any("no OCR engine is installed" in w for w in audit["warnings"])


def test_ocr_max_pages_caps_the_work_and_says_so(tmp_path, fake_engine):
    path = _make_pdf(tmp_path / "many.pdf", [{"image": True} for _ in range(4)])
    pages, audit = pp.parse_pdf_document(path, ocr_max_pages=2)

    assert fake_engine.calls == 2
    assert audit["ocr_pages"] == 2
    assert audit["ocr_skipped_pages"] == 2
    assert audit["ocr_truncated"] is True
    assert len(pages) == 2


def test_low_confidence_pages_are_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pp, "load_ocr_engine", lambda preferred="auto", **kw: _FakeEngine(confidence=0.40)
    )
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    _pages, audit = pp.parse_pdf_document(path, ocr_min_confidence=0.75)

    assert audit["low_confidence_pages"] == [1]


def test_time_budget_stops_ocr_and_records_what_was_left_unread(tmp_path, fake_engine):
    """
    A scanned book can take hours. The budget must be a hard stop, and the
    unread pages must be counted -- otherwise the document looks complete.
    """
    path = _make_pdf(tmp_path / "book.pdf", [{"image": True} for _ in range(3)])
    pages, audit = pp.parse_pdf_document(path, ocr_time_budget_seconds=0)

    assert fake_engine.calls == 0
    assert pages == []
    assert audit["ocr_truncated"] is True
    assert audit["ocr_skipped_pages"] == 3
    assert any("time budget" in w for w in audit["warnings"])


def test_ocr_engine_missing_is_reported_not_crashed(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "load_ocr_engine", lambda preferred="auto", **kw: None)
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    pages, audit = pp.parse_pdf_document(path)

    assert pages == []
    assert audit["ocr_available"] is False
    assert audit["ocr_skipped_pages"] == 1
    assert any("no OCR engine is installed" in w for w in audit["warnings"])


def test_password_protected_pdf_raises_a_clear_error(tmp_path):
    import fitz as _fitz

    path = str(tmp_path / "locked.pdf")
    doc = _fitz.open()
    page = doc.new_page()
    page.insert_textbox(_fitz.Rect(50, 50, 545, 792), _LONG, fontsize=11, fontname="helv")
    doc.save(path, encryption=_fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    doc.close()

    with pytest.raises(ValueError, match="password-protected"):
        pp.parse_pdf_document(path)


def test_preprocessing_escalates_only_when_the_first_pass_is_weak(tmp_path, monkeypatch):
    """
    Deskew and binarise measurably hurt pages that were already clean, so the
    ladder must stop at the first acceptable result.
    """
    engine = _FakeEngine(confidence=0.95)
    monkeypatch.setattr(pp, "load_ocr_engine", lambda preferred="auto", **kw: engine)
    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    _pages, audit = pp.parse_pdf_document(path, ocr_max_attempts=4)

    assert engine.calls == 1
    assert audit["pages"][0]["ocr_attempts"] == 1
    assert audit["pages"][0]["preprocess"] == "none"


def test_progress_callback_reports_every_phase(tmp_path, fake_engine):
    seen = []

    def progress(phase, done, total, detail=""):
        seen.append((phase, done, total))

    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}, {"text": _LONG}])
    pp.parse_pdf_document(path, progress=progress)

    phases = [p[0] for p in seen]
    assert "audit" in phases
    assert "ocr" in phases
    assert phases[-1] == "finalize"
    # done never runs ahead of total, and total is the real page count
    assert all(0 <= done <= total for _phase, done, total in seen)


def test_a_broken_progress_callback_cannot_break_parsing(tmp_path, fake_engine):
    def progress(phase, done, total, detail=""):
        raise RuntimeError("UI blew up")

    path = _make_pdf(tmp_path / "scan.pdf", [{"image": True}])
    pages, audit = pp.parse_pdf_document(path, progress=progress)
    assert len(pages) == 1
    assert audit["ocr_pages"] == 1


def test_empty_pdf_is_reported_not_crashed(tmp_path):
    """
    A zero-page PDF must be reported, not treated as a crash.

    PyMuPDF refuses to *save* a document with no pages, so the file is written
    by hand: a minimal catalog pointing at an empty page tree.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 0 /Kids [] >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )

    path = tmp_path / "empty.pdf"
    path.write_bytes(bytes(out))

    pages, audit = pp.parse_pdf_document(str(path))
    assert pages == []
    assert audit["total_pages"] == 0
    assert audit["warnings"]


# ── parse_file_with_audit dispatch ───────────────────────────────────────────
def test_parse_file_with_audit_returns_no_audit_for_non_pdf(tmp_path):
    from app.utils.parsers import parse_file_with_audit

    path = tmp_path / "notes.md"
    path.write_text("# 标题\n\n正文内容。", encoding="utf-8")
    pages, audit = parse_file_with_audit(str(path))
    assert pages and "标题" in pages[0]["text"]
    assert audit is None


# ── OCR thread cap ───────────────────────────────────────────────────────────
def test_default_thread_floor_is_the_documented_cap():
    """The default must be a real number, not "however many cores exist"."""
    assert pp.RapidOcrEngine.DEFAULT_THREADS == 8


def test_thread_cap_reaches_the_engine(monkeypatch):
    """A caller-supplied cap must arrive at the engine, not be swallowed."""
    seen = {}

    class _Spy(pp.OcrEngine):
        name = "spy"

        def __init__(self, intra_op_threads=None):
            seen["threads"] = intra_op_threads

        def run(self, image_bytes):
            return []

    monkeypatch.setattr(pp, "RapidOcrEngine", _Spy)
    pp.load_ocr_engine("rapidocr", threads=3)
    assert seen["threads"] == 3


def test_zero_threads_is_an_opt_out_not_unset(monkeypatch):
    """
    ``0`` means "let the library decide".

    It used to be collapsed to ``None`` on the way through ``load_ocr_engine``,
    which silently pinned the cap back on and made the escape hatch useless.
    """
    seen = {}

    class _Spy(pp.OcrEngine):
        name = "spy"

        def __init__(self, intra_op_threads=None):
            seen["threads"] = intra_op_threads

        def run(self, image_bytes):
            return []

    monkeypatch.setattr(pp, "RapidOcrEngine", _Spy)
    pp.load_ocr_engine("rapidocr", threads=0)
    assert seen["threads"] == 0


def test_tesseract_is_built_without_the_thread_kwarg(monkeypatch):
    """Tesseract shells out, so passing it a thread hint would be a TypeError."""

    class _Stub(pp.OcrEngine):
        name = "tesseract"

        def __init__(self):
            self.built = True

        def run(self, image_bytes):
            return []

    monkeypatch.setattr(pp, "TesseractEngine", _Stub)
    engine = pp.load_ocr_engine("tesseract", threads=8)
    assert engine is not None and engine.name == "tesseract"


def test_engine_missing_still_falls_back_to_none(monkeypatch):
    class _Broken(pp.OcrEngine):
        name = "broken"

        def __init__(self, intra_op_threads=None):
            raise RuntimeError("model files missing")

        def run(self, image_bytes):
            return []

    monkeypatch.setattr(pp, "RapidOcrEngine", _Broken)
    monkeypatch.setattr(pp, "TesseractEngine", _Broken)
    assert pp.load_ocr_engine("auto", threads=8) is None
