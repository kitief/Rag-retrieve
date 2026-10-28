"""
Layered PDF parsing pipeline.

Real-world PDFs are not one thing. A single book can mix clean digital pages, a
cover that is a photo, a scan of a signature page, and a few pages whose "text
layer" is a broken OCR job that captured six glyphs per page. Feeding all of
that to one OCR model is how you get 4 chunks and an LLM that says "I could not
find that in your documents".

So the pipeline is deliberately staged, and every stage is auditable:

1. **Audit first, never parse blindly** (:func:`audit_page`)
   Every page is classified from cheap signals only -- extracted text length,
   image coverage, junk-character ratio, single-character line count, text
   quality score. No OCR is run during the audit, so auditing a 1400-page book
   takes seconds instead of hours.

   Page kinds:
     * ``digital``  -- a real text layer. Use it; it is exact and free.
     * ``scanned``  -- no usable text layer, page is one big image. Needs OCR.
     * ``hybrid``   -- real text *and* a full-page image (scan + text layer),
                       or a text layer that exists but is corrupt.
     * ``blank``    -- nothing to extract.

2. **Route, do not guess** (:func:`_page_needs_ocr`)
   Only ``scanned`` pages, and ``hybrid`` pages whose text layer fails a quality
   check, are sent to OCR. Digital pages never touch OCR -- OCR is *less*
   accurate than a real text layer, so running it there only loses information.

3. **Preprocess lazily, escalate on failure** (:func:`_preprocess`)
   The first OCR attempt uses the raw 300 DPI render. Deskew / denoise /
   binarise are applied *only* when that attempt comes back low-confidence or
   nearly empty, because aggressive preprocessing measurably hurts pages that
   were already clean.

4. **Keep the evidence** (:class:`OcrBlock`)
   OCR blocks retain their bounding box and confidence, and the run produces a
   JSON-serialisable audit record. Low-confidence pages are reported rather than
   silently accepted, which is what makes the result reviewable.

The public entry point is :func:`parse_pdf_document`, which returns
``(pages, audit)`` where ``pages`` is the ``{text, page, source}`` shape the
chunker already understands and ``audit`` is the report the API stores and the
UI displays.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Page kinds ────────────────────────────────────────────────────────────────
KIND_DIGITAL = "digital"
KIND_SCANNED = "scanned"
KIND_HYBRID = "hybrid"
KIND_BLANK = "blank"

# ── Character classes used by the quality heuristics ──────────────────────────
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_ALNUM_RE = re.compile(r"[0-9A-Za-z]")
#: Private-use area, replacement char and stray control bytes. A healthy text
#: layer has essentially none of these; a broken OCR layer is full of them.
_JUNK_RE = re.compile(r"[\ufffd\ue000-\uf8ff\x00-\x08\x0b\x0e-\x1f]")
#: Sentence terminators, including the full-width CJK forms.
_TERMINAL_RE = re.compile(r"[.。!！?？;；:：…]$")
#: A line that ends like this is a wrapped fragment, not a paragraph end.
_HYPHEN_RE = re.compile(r"[A-Za-z]-$")

#: Anything shorter than this on a full-page image is a stamp, a page number or
#: a broken OCR layer -- never the page's real content.
DEFAULT_MIN_TEXT_CHARS = 200
#: Below this quality score a text layer is treated as corrupt.
QUALITY_FLOOR = 0.35


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class OcrBlock:
    """One recognised text block, with the evidence needed to audit it."""

    text: str
    bbox: Tuple[float, float, float, float]
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "bbox": [round(v, 1) for v in self.bbox],
            "conf": round(self.confidence, 4),
        }


@dataclass
class PageAudit:
    """The audit verdict for a single page."""

    page: int
    kind: str
    chars: int = 0
    image_coverage: float = 0.0
    junk_ratio: float = 0.0
    cjk_ratio: float = 0.0
    single_char_lines: int = 0
    lines: int = 0
    quality: float = 0.0
    needs_ocr: bool = False
    ocr_used: bool = False
    ocr_attempts: int = 0
    ocr_confidence: Optional[float] = None
    preprocess: Optional[str] = None
    text_source: str = "text_layer"
    out_chars: int = 0
    note: str = ""

    @property
    def notable(self) -> bool:
        """
        True when this page deserves a second look in the persisted report.

        Storing all 1439 verdicts of a book would bloat the row for no benefit --
        the aggregate counts already say "1438 pages were scans". What is worth
        keeping is the pages that were OCR'd (so their confidence can be
        reviewed), that were skipped or failed, or that carry a note.
        """
        return bool(self.ocr_used or self.needs_ocr or self.note)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "kind": self.kind,
            "chars": self.chars,
            "image_coverage": round(self.image_coverage, 3),
            "junk_ratio": round(self.junk_ratio, 4),
            "cjk_ratio": round(self.cjk_ratio, 4),
            "single_char_lines": self.single_char_lines,
            "lines": self.lines,
            "quality": round(self.quality, 3),
            "needs_ocr": self.needs_ocr,
            "ocr_used": self.ocr_used,
            "ocr_attempts": self.ocr_attempts,
            "ocr_confidence": (
                None if self.ocr_confidence is None else round(self.ocr_confidence, 4)
            ),
            "preprocess": self.preprocess,
            "text_source": self.text_source,
            "out_chars": self.out_chars,
            "note": self.note,
        }


@dataclass
class PdfAudit:
    """Whole-document audit report, JSON-serialisable and shown in the UI."""

    filename: str
    total_pages: int = 0
    digital_pages: int = 0
    scanned_pages: int = 0
    hybrid_pages: int = 0
    blank_pages: int = 0
    ocr_pages: int = 0
    ocr_failed_pages: int = 0
    ocr_skipped_pages: int = 0
    ocr_truncated: bool = False
    ocr_engine: Optional[str] = None
    ocr_available: bool = True
    mean_confidence: Optional[float] = None
    low_confidence_pages: List[int] = field(default_factory=list)
    text_chars: int = 0
    duration_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    pages: List[PageAudit] = field(default_factory=list)

    def to_dict(self, *, page_mode: str = "notable") -> Dict[str, Any]:
        """
        Serialise the report.

        Args:
            page_mode: Which per-page records to include.
                ``"all"``   -- every page (large: ~250 bytes/page, so a
                               1400-page book costs a third of a megabyte).
                ``"notable"`` (default) -- only pages worth a second look:
                               OCR'd, skipped, failed, or carrying a note. This
                               is what gets persisted, because the aggregate
                               counts already describe the boring pages.
                ``"none"``  -- aggregates only.
        """
        data: Dict[str, Any] = {
            "filename": self.filename,
            "total_pages": self.total_pages,
            "digital_pages": self.digital_pages,
            "scanned_pages": self.scanned_pages,
            "hybrid_pages": self.hybrid_pages,
            "blank_pages": self.blank_pages,
            "ocr_pages": self.ocr_pages,
            "ocr_failed_pages": self.ocr_failed_pages,
            "ocr_skipped_pages": self.ocr_skipped_pages,
            "ocr_truncated": self.ocr_truncated,
            "ocr_engine": self.ocr_engine,
            "ocr_available": self.ocr_available,
            "mean_confidence": (
                None if self.mean_confidence is None else round(self.mean_confidence, 4)
            ),
            "low_confidence_pages": self.low_confidence_pages[:50],
            "text_chars": self.text_chars,
            "duration_seconds": round(self.duration_seconds, 2),
            "warnings": self.warnings,
        }
        if page_mode == "all":
            data["pages"] = [p.to_dict() for p in self.pages]
        elif page_mode == "notable":
            data["pages"] = [p.to_dict() for p in self.pages if p.notable]
        else:
            data["pages"] = []
        return data


# ── Text metrics ──────────────────────────────────────────────────────────────
def _ratio(pattern: re.Pattern[str], text: str, total: int) -> float:
    return len(pattern.findall(text)) / total if total else 0.0


def text_quality(text: str) -> float:
    """
    Score a text layer from 0 (garbage) to 1 (clean prose).

    Deliberately blunt: it only has to separate "this is a real page of text"
    from "this is six glyphs of a failed OCR job", and both of those look very
    different on every one of these signals.
    """
    stripped = text.strip()
    n = len(stripped)
    if n == 0:
        return 0.0

    junk = _ratio(_JUNK_RE, stripped, n)
    cjk = _ratio(_CJK_RE, stripped, n)
    alnum = _ratio(_ALNUM_RE, stripped, n)
    lines = [ln.strip() for ln in stripped.split("\n") if ln.strip()]
    short_lines = sum(1 for ln in lines if len(ln) <= 2)
    short_ratio = short_lines / len(lines) if lines else 0.0

    # How much real, non-space content there is (saturates at 400 chars).
    volume = min(1.0, n / 400.0)
    # Letters/digits: a page of punctuation soup scores near zero here.
    substance = min(1.0, cjk + alnum)

    score = 0.45 * volume + 0.35 * substance + 0.20 * (1.0 - short_ratio)
    score -= 2.0 * junk
    return max(0.0, min(1.0, score))


def _image_coverage(page: Any, fitz: Any) -> float:
    """Largest single image's share of the page area (0..1)."""
    try:
        area = abs(page.rect)
        if area <= 0:
            return 0.0
        best = 0.0
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if not bbox:
                continue
            best = max(best, abs(fitz.Rect(bbox)) / area)
        return min(1.0, best)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PDF] image coverage failed on page %s: %s", page.number + 1, exc)
        return 0.0


# ── Stage 1: audit ────────────────────────────────────────────────────────────
def audit_page(page: Any, page_number: int, fitz: Any, *, min_text_chars: int = DEFAULT_MIN_TEXT_CHARS) -> Tuple[PageAudit, str]:
    """
    Classify one page using only the text layer and image geometry.

    Returns the audit record and the raw text layer (which the caller reuses if
    the verdict says the text layer is trustworthy -- extracting it twice would
    be wasteful on a 1400-page document).
    """
    try:
        raw_text = page.get_text("text", sort=True) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PDF] text extraction failed on page %d: %s", page_number, exc)
        raw_text = ""

    stripped = raw_text.strip()
    n = len(stripped)
    coverage = _image_coverage(page, fitz)

    lines = [ln.strip() for ln in stripped.split("\n") if ln.strip()]
    audit = PageAudit(
        page=page_number,
        kind=KIND_BLANK,
        chars=n,
        image_coverage=coverage,
        junk_ratio=_ratio(_JUNK_RE, stripped, n),
        cjk_ratio=_ratio(_CJK_RE, stripped, n),
        single_char_lines=sum(1 for ln in lines if len(ln) <= 2),
        lines=len(lines),
        quality=text_quality(stripped),
    )

    if n == 0:
        # No text at all. A full-page image means a scan; otherwise the page is
        # genuinely empty (or vector-only artwork we cannot read anyway).
        audit.kind = KIND_SCANNED if coverage >= 0.5 else KIND_BLANK
        audit.needs_ocr = audit.kind == KIND_SCANNED
        if audit.kind == KIND_BLANK:
            audit.text_source = "none"
            audit.note = "no text layer and no page-sized image"
        return audit, raw_text

    if coverage >= 0.5 and n < min_text_chars:
        # A handful of glyphs sitting on top of a full-page scan. This is the
        # classic "bad hidden OCR layer": a previous tool captured a few
        # characters and left everything else as pixels. Trusting it is exactly
        # how a page ends up contributing 6 characters to the index.
        audit.kind = KIND_SCANNED
        audit.needs_ocr = True
        audit.note = f"text layer holds only {n} chars over a full-page image"
        return audit, raw_text

    if audit.junk_ratio >= 0.03 or audit.quality < QUALITY_FLOOR:
        # Text exists but is not usable prose (mojibake, glyph soup).
        audit.kind = KIND_HYBRID
        audit.needs_ocr = True
        audit.note = "text layer failed the quality check"
        return audit, raw_text

    if coverage >= 0.5:
        # A real text layer plus a full-page background image. The text layer is
        # exact, so keep it; OCR could only make it worse.
        audit.kind = KIND_HYBRID
        audit.needs_ocr = False
        audit.note = "text layer present over a page-sized image"
        return audit, raw_text

    audit.kind = KIND_DIGITAL
    audit.needs_ocr = False
    return audit, raw_text


# ── Stage 2: OCR engines ──────────────────────────────────────────────────────
class OcrEngine:
    """Thin adapter so RapidOCR and Tesseract share one call signature."""

    name: str = "none"

    def run(self, image_bytes: bytes) -> List[OcrBlock]:  # pragma: no cover - interface
        raise NotImplementedError


class RapidOcrEngine(OcrEngine):
    """
    RapidOCR (PaddleOCR models exported to ONNX).

    Chosen over Tesseract for the bundled build: the models ship inside the
    wheel, so there is no separate system binary to install, and its Chinese
    recognition is markedly better than `tesseract --lang eng` on CJK scans.

    The intra-op thread count is capped deliberately. onnxruntime otherwise
    opens one thread per logical core (16 here), and on a busy machine that is
    slower than a smaller pool: measured over the same six book pages, the
    default took 12.4 s/page while a cap of 8 took 7.5 s/page -- 1.6x faster,
    reproducibly, across three interleaved runs. Oversubscribing the cores makes
    the scheduler thrash. A process pool measured faster still (6.1 s/page) but
    is not used here: the backend ships as a frozen onedir build, and
    multiprocessing in a frozen app needs `freeze_support()` plus a top-level
    entry point that the Tauri shell controls, so the gain did not justify the
    packaging risk.
    """

    name = "rapidocr"

    #: Upper bound on onnxruntime's intra-op threads. See the class docstring.
    DEFAULT_THREADS = 8

    def __init__(self, intra_op_threads: Optional[int] = None) -> None:
        """
        Args:
            intra_op_threads: Threads for onnxruntime. ``None`` uses
                :attr:`DEFAULT_THREADS`, ``0`` leaves the choice entirely to
                RapidOCR (which asks for one thread per core).
        """
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: heavy

        cores = os.cpu_count() or 1
        if intra_op_threads == 0:
            # Explicit opt-out: let the library pick.
            self._ocr = RapidOCR()
            self.threads = 0
            return

        requested = self.DEFAULT_THREADS if intra_op_threads is None else intra_op_threads
        # Never ask for more threads than there are cores, and never fewer than
        # one: on a 4-core laptop this is a no-op, on a 16-core one it matters.
        threads = max(1, min(requested, cores))

        try:
            self._ocr = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)
        except TypeError:
            # Older RapidOCR builds take no thread kwargs; their default is fine.
            logger.info("[PDF] RapidOCR does not accept thread options; using defaults")
            self._ocr = RapidOCR()
            threads = 0
        self.threads = threads

    def run(self, image_bytes: bytes) -> List[OcrBlock]:
        result, _elapse = self._ocr(image_bytes)
        blocks: List[OcrBlock] = []
        for item in result or []:
            try:
                box, text, score = item[0], item[1], item[2]
            except (IndexError, TypeError):
                continue
            if not text or not str(text).strip():
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            blocks.append(
                OcrBlock(
                    text=str(text).strip(),
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    confidence=float(score),
                )
            )
        return blocks


class TesseractEngine(OcrEngine):
    """Fallback for environments that already have Tesseract installed."""

    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract  # noqa: F401  (probe only)
        from PIL import Image  # noqa: F401

        self._pytesseract = pytesseract

    def run(self, image_bytes: bytes) -> List[OcrBlock]:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        data = self._pytesseract.image_to_data(
            image, lang="eng", config="--psm 3", output_type=self._pytesseract.Output.DICT
        )
        # Reassemble words into lines, since image_to_data is word-level.
        lines: Dict[Tuple[int, int, int], List[Tuple[str, float, int, int, int, int]]] = {}
        for i, word in enumerate(data.get("text", [])):
            if not str(word).strip():
                continue
            try:
                conf = float(data["conf"][i])
            except (KeyError, TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(
                (
                    str(word).strip(),
                    conf,
                    int(data["left"][i]),
                    int(data["top"][i]),
                    int(data["width"][i]),
                    int(data["height"][i]),
                )
            )

        blocks: List[OcrBlock] = []
        for key in sorted(lines):
            words = lines[key]
            text = " ".join(w[0] for w in words)
            conf = sum(w[1] for w in words) / len(words) / 100.0
            x0 = min(w[2] for w in words)
            y0 = min(w[3] for w in words)
            x1 = max(w[2] + w[4] for w in words)
            y1 = max(w[3] + w[5] for w in words)
            blocks.append(
                OcrBlock(text=text, bbox=(float(x0), float(y0), float(x1), float(y1)), confidence=conf)
            )
        return blocks


def load_ocr_engine(
    preferred: str = "auto", *, threads: Optional[int] = None
) -> Optional[OcrEngine]:
    """
    Build the OCR engine, honouring ``preferred`` but always degrading safely.

    ``auto`` prefers RapidOCR (self-contained) and falls back to Tesseract.
    ``threads`` caps the engine's intra-op threads: ``None`` means "engine
    default", ``0`` means "let onnxruntime decide", any other number is the cap.
    Returns ``None`` when neither is installed -- the caller records that in the
    audit so the user learns *why* a scanned page produced no text, instead of
    the document silently ingesting as empty.
    """
    # 0 must survive as 0: it is the documented opt-out, not "unset". Collapsing
    # it to None here would silently re-apply the cap and kill the escape hatch.
    order: List[type[OcrEngine]]
    if preferred == "rapidocr":
        order = [RapidOcrEngine]
    elif preferred == "tesseract":
        order = [TesseractEngine]
    else:
        order = [RapidOcrEngine, TesseractEngine]

    for cls in order:
        try:
            # Only the ONNX engine takes a thread hint; Tesseract runs as a
            # subprocess, so there is nothing to cap there.
            takes_threads = issubclass(cls, RapidOcrEngine)
            engine = cls(intra_op_threads=threads) if takes_threads else cls()
            logger.info(
                "[PDF] OCR engine ready: %s (intra_op_threads=%s)",
                engine.name,
                getattr(engine, "threads", "n/a"),
            )
            return engine
        except Exception as exc:
            logger.info("[PDF] OCR engine %s unavailable: %s", cls.__name__, exc)
    logger.warning("[PDF] No OCR engine available; scanned pages cannot be read.")
    return None


# ── Stage 3: rasterise + lazy preprocessing ──────────────────────────────────
def _render(page: Any, dpi: int, max_side: int) -> Tuple[Any, Any]:
    """Rasterise a page to a PIL image, downscaling oversized renders."""
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi, alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if max_side and max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    return image, pix


def _deskew(image: Any) -> Any:
    """
    Straighten a tilted scan.

    Only called after a first attempt looked bad, because estimating the angle
    costs a rotation pass and rotating an already-straight page resamples the
    glyphs for nothing.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:  # pragma: no cover - cv2 is optional
        return image

    try:
        array = np.array(image.convert("L"))
        # Invert so ink is white on black, then find the dominant text angle.
        edges = cv2.Canny(array, 50, 150)
        coords = np.column_stack(np.where(edges > 0))
        if len(coords) < 100:
            return image
        angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.3 or abs(angle) > 15:
            # 0 means "already straight"; >15 usually means minAreaRect latched
            # onto something that is not text, so rotating would make it worse.
            return image
        from PIL import Image as _Image

        return image.rotate(angle, resample=_Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PDF] deskew failed: %s", exc)
        return image


def _denoise_and_binarize(image: Any) -> Any:
    """Denoise then adaptively threshold, for grainy low-contrast scans."""
    try:
        import cv2
        import numpy as np
    except ImportError:  # pragma: no cover - cv2 is optional
        return image

    try:
        array = np.array(image.convert("L"))
        array = cv2.fastNlMeansDenoising(array, None, 10, 7, 21)
        array = cv2.adaptiveThreshold(
            array, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
        )
        from PIL import Image as _Image

        return _Image.fromarray(array)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PDF] denoise/binarize failed: %s", exc)
        return image


#: Escalation ladder. Index 0 is the raw render; later steps are only paid for
#: when the previous one disappointed.
_PREPROCESS_STEPS: Tuple[Tuple[str, Optional[Callable[[Any], Any]]], ...] = (
    ("none", None),
    ("deskew", _deskew),
    ("denoise+binarize", _denoise_and_binarize),
    ("deskew+denoise+binarize", lambda img: _denoise_and_binarize(_deskew(img))),
)


def _encode(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _ocr_page(
    page: Any,
    engine: OcrEngine,
    *,
    dpi: int,
    max_side: int,
    min_confidence: float,
    max_attempts: int,
) -> Tuple[List[OcrBlock], float, int, str]:
    """
    OCR one page, escalating preprocessing only while the result is poor.

    Returns ``(blocks, mean_confidence, attempts, preprocess_name)``.
    """
    image, _pix = _render(page, dpi, max_side)

    best: List[OcrBlock] = []
    best_conf = 0.0
    best_step = "none"
    attempts = 0

    for name, transform in _PREPROCESS_STEPS[: max(1, max_attempts)]:
        candidate = image if transform is None else transform(image)
        attempts += 1
        try:
            blocks = engine.run(_encode(candidate))
        except Exception as exc:
            logger.warning("[PDF] OCR attempt %d (%s) failed on page %d: %s", attempts, name, page.number + 1, exc)
            blocks = []

        if blocks:
            mean_conf = sum(b.confidence for b in blocks) / len(blocks)
            chars = sum(len(b.text) for b in blocks)
        else:
            mean_conf = 0.0
            chars = 0

        if (mean_conf, chars) > (best_conf, sum(len(b.text) for b in best)):
            best, best_conf, best_step = blocks, mean_conf, name

        # Good enough: stop paying for more preprocessing.
        if blocks and mean_conf >= min_confidence and chars >= 20:
            break
        if not blocks and transform is not None:
            continue
        if blocks and mean_conf >= min_confidence * 0.8:
            break

    return best, best_conf, attempts, best_step


# ── Stage 4: text assembly ───────────────────────────────────────────────────
def _reflow_cjk(lines: List[str]) -> str:
    """
    Join wrapped CJK lines back into paragraphs.

    Chinese typesetting breaks lines mid-sentence, so a scan read line by line
    produces text whose sentence boundaries are all wrong -- which then poisons
    the chunker (it splits on sentence ends). We re-join until a line actually
    ends with terminal punctuation.
    """
    paragraphs: List[str] = []
    buffer = ""
    for line in lines:
        buffer += line
        if _TERMINAL_RE.search(line):
            paragraphs.append(buffer)
            buffer = ""
    if buffer.strip():
        paragraphs.append(buffer)
    return "\n".join(p for p in paragraphs if p.strip())


def _reflow_latin(lines: List[str]) -> str:
    """Undo hard wrapping, including hyphenated breaks."""
    paragraphs: List[str] = []
    buffer = ""
    for line in lines:
        if _HYPHEN_RE.search(line):
            buffer += line[:-1]
            continue
        buffer = f"{buffer} {line}".strip() if buffer else line
        if _TERMINAL_RE.search(line) or len(line) < 40:
            paragraphs.append(buffer)
            buffer = ""
    if buffer.strip():
        paragraphs.append(buffer)
    return "\n".join(p for p in paragraphs if p.strip())


def reflow_ocr_text(text: str) -> str:
    """Re-assemble OCR line output into paragraphs, CJK-aware."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    joined = "".join(lines)
    cjk_ratio = _ratio(_CJK_RE, joined, len(joined)) if joined else 0.0
    return _reflow_cjk(lines) if cjk_ratio >= 0.3 else _reflow_latin(lines)


def _tables_to_markdown(page: Any, page_text: str, max_tables: int = 20) -> str:
    """
    Extract ruled tables as Markdown, skipping any whose text is already in the
    page's text layer (which it usually is -- no point indexing it twice).
    """
    try:
        finder = page.find_tables()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[PDF] table detection failed on page %d: %s", page.number + 1, exc)
        return ""

    normalised_page = re.sub(r"\s+", "", page_text)
    chunks: List[str] = []
    for table in list(getattr(finder, "tables", []))[:max_tables]:
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue
        cleaned = [
            [(cell or "").strip().replace("\n", " ") for cell in row]
            for row in rows
        ]
        if not any(any(cell for cell in row) for row in cleaned):
            continue
        flat = re.sub(r"\s+", "", "".join("".join(row) for row in cleaned))
        # If most of the table's text is already in the page layer, it is a
        # duplicate -- the text layer wins because it is exact.
        if flat and len(flat) > 20 and flat[:40] in normalised_page:
            continue
        lines = ["| " + " | ".join(row) + " |" for row in cleaned if any(row)]
        if len(lines) < 2:
            continue
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def _blocks_to_text(blocks: List[OcrBlock]) -> str:
    """
    Order OCR blocks into reading order.

    RapidOCR returns blocks in a roughly top-to-bottom order, but two-column
    pages come back interleaved. Sorting by row band first, then left-to-right
    within a band, restores the natural reading order for the common cases
    without pretending to do real layout analysis.
    """
    if not blocks:
        return ""
    heights = [max(1.0, b.bbox[3] - b.bbox[1]) for b in blocks]
    median_h = sorted(heights)[len(heights) // 2]
    band = max(8.0, median_h * 0.6)

    ordered = sorted(blocks, key=lambda b: (round(b.bbox[1] / band), b.bbox[0]))
    lines: List[str] = []
    current_band = None
    current_line: List[str] = []
    for block in ordered:
        key = round(block.bbox[1] / band)
        if current_band is None or key == current_band:
            current_line.append(block.text)
        else:
            lines.append("".join(current_line) if _looks_cjk(current_line) else " ".join(current_line))
            current_line = [block.text]
        current_band = key
    if current_line:
        lines.append("".join(current_line) if _looks_cjk(current_line) else " ".join(current_line))
    return "\n".join(lines)


def _looks_cjk(parts: List[str]) -> bool:
    joined = "".join(parts)
    return bool(joined) and _ratio(_CJK_RE, joined, len(joined)) >= 0.3


# ── Public entry point ────────────────────────────────────────────────────────
ProgressCallback = Callable[[str, int, int, str], None]


def parse_pdf_document(
    path: str,
    *,
    progress: Optional[ProgressCallback] = None,
    ocr_enabled: bool = True,
    ocr_engine: str = "auto",
    ocr_dpi: int = 300,
    ocr_max_side: int = 1600,
    ocr_max_pages: int = 0,
    ocr_time_budget_seconds: int = 1800,
    ocr_min_confidence: float = 0.75,
    ocr_max_attempts: int = 3,
    ocr_threads: int = RapidOcrEngine.DEFAULT_THREADS,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    extract_tables: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parse a PDF in layers: audit every page, OCR only what needs it.

    Args:
        progress: Called as ``progress(phase, done, total, detail)``. Phases are
            ``audit``, ``ocr`` and ``finalize``. Used to drive the UI progress
            bar; OCR of a long scan can legitimately take many minutes.
        ocr_max_pages: Stop OCR after this many pages (0 = no cap). Pages left
            over are counted in ``ocr_skipped_pages`` and flagged in the audit.
        ocr_time_budget_seconds: Wall-clock ceiling for the OCR stage. This is
            the safety valve that keeps one 1400-page scan from monopolising the
            worker for hours.
        ocr_threads: onnxruntime intra-op threads for the OCR engine (0 = let the
            library decide). 8 measured 1.6x faster than the library default on a
            16-core machine; see ``RapidOcrEngine``.

    Returns:
        ``(pages, audit)`` -- ``pages`` is the usual ``{text, page, source}``
        list; ``audit`` is a JSON-serialisable report including per-page
        verdicts, OCR confidences and any warnings.
    """
    import fitz

    started = time.time()
    source = os.path.basename(path)
    audit = PdfAudit(filename=source)

    def notify(phase: str, done: int, total: int, detail: str = "") -> None:
        if progress is None:
            return
        try:
            progress(phase, done, total, detail)
        except Exception:  # pragma: no cover - a UI callback must never break parsing
            logger.debug("[PDF] progress callback raised", exc_info=True)

    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            raise ValueError("This PDF is password-protected and cannot be parsed.")

        total = len(doc)
        audit.total_pages = total
        if total == 0:
            audit.warnings.append("The PDF reports zero pages.")
            return [], audit.to_dict()

        # ── Stage 1: audit every page (no OCR, so this stays cheap) ──────────
        audits: List[PageAudit] = []
        texts: List[str] = []
        for i in range(total):
            page_audit, raw = audit_page(doc.load_page(i), i + 1, fitz, min_text_chars=min_text_chars)
            audits.append(page_audit)
            texts.append(raw)
            if (i + 1) % 25 == 0 or i + 1 == total:
                notify("audit", i + 1, total, page_audit.kind)

        audit.digital_pages = sum(1 for a in audits if a.kind == KIND_DIGITAL)
        audit.scanned_pages = sum(1 for a in audits if a.kind == KIND_SCANNED)
        audit.hybrid_pages = sum(1 for a in audits if a.kind == KIND_HYBRID)
        audit.blank_pages = sum(1 for a in audits if a.kind == KIND_BLANK)

        # ── Stage 2: OCR only the pages that need it ─────────────────────────
        pending = [a for a in audits if a.needs_ocr]
        engine: Optional[OcrEngine] = None
        if pending and not ocr_enabled:
            # "Disabled" and "not installed" are different problems with
            # different fixes, so they must not share a flag.
            audit.ocr_skipped_pages = len(pending)
            audit.warnings.append(
                f"{len(pending)} page(s) need OCR but OCR is disabled; they were skipped."
            )
        elif pending:
            engine = load_ocr_engine(ocr_engine, threads=ocr_threads)
            if engine is None:
                audit.ocr_available = False
                audit.ocr_skipped_pages = len(pending)
                audit.warnings.append(
                    f"{len(pending)} page(s) need OCR but no OCR engine is installed."
                )

        if engine is not None:
            audit.ocr_engine = engine.name
            budget_end = started + max(0, ocr_time_budget_seconds)
            confidences: List[float] = []
            done = 0
            for page_audit in pending:
                if ocr_max_pages and audit.ocr_pages >= ocr_max_pages:
                    audit.ocr_truncated = True
                    audit.warnings.append(
                        f"OCR stopped after {audit.ocr_pages} page(s) (PDF_OCR_MAX_PAGES="
                        f"{ocr_max_pages}); {len(pending) - done} page(s) were left unread."
                    )
                    audit.ocr_skipped_pages = len(pending) - done
                    break
                if time.time() > budget_end:
                    audit.ocr_truncated = True
                    audit.warnings.append(
                        "OCR hit the time budget; the remaining pages were left unread. "
                        "Raise PDF_OCR_TIME_BUDGET_SECONDS to cover the whole document."
                    )
                    audit.ocr_skipped_pages = len(pending) - done
                    break

                page = doc.load_page(page_audit.page - 1)
                blocks, mean_conf, attempts, step = _ocr_page(
                    page,
                    engine,
                    dpi=ocr_dpi,
                    max_side=ocr_max_side,
                    min_confidence=ocr_min_confidence,
                    max_attempts=ocr_max_attempts,
                )
                done += 1
                page_audit.ocr_used = True
                page_audit.ocr_attempts = attempts
                page_audit.preprocess = step
                page_audit.ocr_confidence = mean_conf if blocks else None

                if blocks:
                    ocr_text = _blocks_to_text(blocks)
                    reflowed = reflow_ocr_text(ocr_text)
                    # Keep whichever is more substantial: on a page with a
                    # fragment text layer, OCR is the only real source.
                    if len(reflowed.strip()) > len(texts[page_audit.page - 1].strip()):
                        texts[page_audit.page - 1] = reflowed
                        page_audit.text_source = "ocr"
                    else:
                        page_audit.text_source = "text_layer"
                    confidences.append(mean_conf)
                    audit.ocr_pages += 1
                    if mean_conf < ocr_min_confidence:
                        audit.low_confidence_pages.append(page_audit.page)
                else:
                    page_audit.text_source = "none"
                    page_audit.note = (page_audit.note + "; " if page_audit.note else "") + "OCR found no text"
                    audit.ocr_failed_pages += 1

                notify("ocr", done, len(pending), f"page {page_audit.page}")

            if confidences:
                audit.mean_confidence = sum(confidences) / len(confidences)

        # ── Stage 3: assemble pages, adding tables where useful ──────────────
        pages: List[Dict[str, Any]] = []
        for page_audit, text in zip(audits, texts):
            assembled = text.strip()
            if extract_tables and page_audit.kind in (KIND_DIGITAL, KIND_HYBRID):
                markdown = _tables_to_markdown(doc.load_page(page_audit.page - 1), assembled)
                if markdown:
                    assembled = f"{assembled}\n\n{markdown}" if assembled else markdown
                    page_audit.note = (page_audit.note + "; " if page_audit.note else "") + "tables extracted"

            page_audit.out_chars = len(assembled)
            if assembled:
                pages.append({"text": assembled, "page": page_audit.page, "source": source})

        audit.pages = audits
        audit.text_chars = sum(a.out_chars for a in audits)
        audit.duration_seconds = time.time() - started

        # Tell the user the one thing they most need to know.
        if audit.total_pages and audit.ocr_pages == 0 and audit.scanned_pages:
            if audit.ocr_available:
                audit.warnings.append(
                    "This PDF looks like a scan and no page could be read as text."
                )
        if audit.text_chars < 200 and audit.total_pages > 3:
            audit.warnings.append(
                "Very little text was recovered from this document; answers may be unreliable."
            )

        notify("finalize", total, total, f"{len(pages)} pages with text")
        logger.info(
            "[PDF] %s: %d/%d pages kept, %d OCR'd, %d chars, %.1fs",
            source, len(pages), total, audit.ocr_pages, audit.text_chars, audit.duration_seconds,
        )
        return pages, audit.to_dict()
    finally:
        doc.close()
