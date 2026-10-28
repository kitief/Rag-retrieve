from typing import Any, Callable, Dict, List, Optional, Tuple
import logging
import os
import threading

logger = logging.getLogger(__name__)

# ── Capability flags ─────────────────────────────────────────────────────────
# Audio/video transcription and image/scanned-PDF OCR are shelved for now.
# The parsing code below is intentionally kept intact so these capabilities can
# be re-enabled later by flipping ENABLE_AUDIO_VIDEO_UPLOADS /
# ENABLE_OCR_UPLOADS back to True in .env — no rewrite required.
def _audio_video_enabled() -> bool:
    from app.config import get_settings
    return bool(get_settings().enable_audio_video_uploads)


def _ocr_enabled() -> bool:
    from app.config import get_settings
    return bool(get_settings().enable_ocr_uploads)


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
TEXT_EXTENSIONS = {".txt", ".text", ".md", ".markdown"}
CSV_EXTENSIONS = {".csv", ".tsv"}

#: Formats the parser can extract text from today.
#:
#: ``.md``/``.markdown``/``.txt`` go through :func:`parse_text`, which keeps the
#: raw source (headings, lists, code fences). That is deliberate: the chunker
#: splits on paragraphs, and stripping the markup would discard the heading
#: structure that later gives the model cheap context.
#:
#: ``.csv``/``.tsv`` use :func:`parse_csv`, which keeps each row intact and
#: repeats the header on every pseudo-page so a retrieved chunk still says which
#: column a bare value belongs to.
#:
#: ``.doc`` (the legacy binary Word format) is handled by
#: :mod:`app.utils.doc_legacy` -- a pure-Python OLE2 + piece-table reader. It
#: needs no extra dependency, which matters because the app ships as an offline
#: PyInstaller bundle where adding ``olefile`` or COM automation is not free.
CORE_EXTENSIONS = {
    ".pdf",
    ".pptx",
    ".ppt",
    ".docx",
    ".doc",
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".csv",
    ".tsv",
}

SHELVED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

#: Extensions the upload endpoint currently accepts.
SUPPORTED_EXTENSIONS = set(CORE_EXTENSIONS)
if _audio_video_enabled():
    SUPPORTED_EXTENSIONS |= SHELVED_EXTENSIONS


def is_extension_allowed(ext: str) -> bool:
    """Return True when the given extension may be uploaded right now."""
    ext = ext.lower()
    if ext in CORE_EXTENSIONS:
        return True
    if ext in SHELVED_EXTENSIONS:
        return _audio_video_enabled()
    return False


def parse_file(path: str) -> List[Dict[str, Any]]:
    """Dispatch to the right parser based on extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(path)
    elif ext in {".pptx", ".ppt"}:
        return parse_pptx(path)
    elif ext in CSV_EXTENSIONS:
        return parse_csv(path)
    elif ext in TEXT_EXTENSIONS:
        return parse_text(path)
    elif ext == ".docx":
        return parse_docx(path)
    elif ext == ".doc":
        return parse_doc(path)
    elif ext in IMAGE_EXTENSIONS:
        return parse_image(path)
    elif ext in AUDIO_EXTENSIONS:
        if not _audio_video_enabled():
            raise ValueError(
                "Audio transcription is currently disabled (ENABLE_AUDIO_VIDEO_UPLOADS=false)."
            )
        return parse_audio(path)
    elif ext in VIDEO_EXTENSIONS:
        if not _audio_video_enabled():
            raise ValueError(
                "Video transcription is currently disabled (ENABLE_AUDIO_VIDEO_UPLOADS=false)."
            )
        return parse_video(path)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

def _paginate_blocks(blocks: List[str], page_size: int = 2000) -> List[str]:
    """
    Group text blocks into pseudo-pages of roughly ``page_size`` characters.

    Blocks are never split unless a single block is longer than ``page_size``
    (a huge Markdown table, for instance). Keeping blocks whole means a chunk
    boundary can fall between paragraphs rather than mid-sentence, which is
    what the chunker downstream expects.
    """
    pages: List[str] = []
    current: List[str] = []
    current_len = 0

    for block in blocks:
        if not block:
            continue
        if len(block) > page_size:
            # Flush what we have, then hard-split the oversized block.
            if current:
                pages.append("\n\n".join(current))
                current, current_len = [], 0
            for i in range(0, len(block), page_size):
                piece = block[i : i + page_size].strip()
                if piece:
                    pages.append(piece)
            continue
        if current_len + len(block) > page_size and current:
            pages.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += len(block) + 2  # +2 for the joining blank line

    if current:
        pages.append("\n\n".join(current))
    return [p for p in pages if p.strip()]


def _read_text_file(path: str) -> str:
    """
    Read a text file, trying the encodings this project actually meets.

    UTF-8 first (the common case), then GB18030 for notes saved by Chinese
    Windows editors, then UTF-16 for files with a wide-character BOM. Windows
    exports also frequently start with a UTF-8 BOM, which ``utf-8-sig`` strips.
    """
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("Failed to read %s: %s", path, exc)
            return ""

    # Last resort: decode as UTF-8 with replacement so we still get something
    # searchable instead of dropping the file entirely.
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def _text_blocks(content: str) -> List[str]:
    """
    Split plain text / Markdown into paragraph blocks for the chunker.

    Blank-line separated paragraphs are the norm for Markdown. Plain ``.txt``
    files are less disciplined: plenty of them use a single newline per line and
    never a blank line at all, and treating such a file as one giant block would
    make :func:`_paginate_blocks` cut it mid-sentence at the 2000-character mark.
    So when blank-line splitting produces suspiciously few blocks, fall back to
    one block per line.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    paragraphs = [b.strip() for b in normalized.split("\n\n")]
    paragraphs = [b for b in paragraphs if b]

    # A single paragraph for a multi-line file means the blank-line convention is
    # absent -- re-split on line breaks so chunks still land on real boundaries.
    if len(paragraphs) <= 1 and normalized.count("\n") >= 3:
        paragraphs = [line.strip() for line in normalized.split("\n") if line.strip()]

    return paragraphs


def parse_text(path: str) -> List[Dict[str, Any]]:
    """
    Plain text or Markdown extraction.

    The source is kept verbatim. For Markdown that preserves headings, lists and
    fenced code, all of which help the model understand the document far more
    than a flattened wall of text would. Only page-splitting happens here.
    """
    logger.info("Parsing text/markdown: %s", path)
    source = os.path.basename(path)

    content = _read_text_file(path)
    if not content.strip():
        return []

    blocks = _text_blocks(content)
    return [
        {"text": text, "page": i, "source": source}
        for i, text in enumerate(_paginate_blocks(blocks), start=1)
    ]


def _docx_blocks(path: str) -> List[str]:
    """
    Return the document body as an ordered list of text blocks.

    Uses python-docx, which preserves paragraph order and exposes tables as
    objects; the plain ``doc.paragraphs`` iteration silently drops every table,
    and study material is full of them. Each table is flattened into pipe-
    separated rows so the values stay associated with their header column.
    """
    import docx
    from docx.document import Document as _DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(path)
    blocks: List[str] = []

    def _emit_table(table: Table) -> None:
        rows: List[str] = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            blocks.append("\n".join(rows))

    # Walk the body in document order so a table stays next to the paragraph
    # that introduces it.
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, doc).text.strip()
            if text:
                blocks.append(text)
        elif child.tag.endswith("}tbl"):
            _emit_table(Table(child, doc))

    if blocks:
        return blocks

    # Some generators (and python-docx on odd inputs) leave body children in a
    # shape the walk above does not recognise; fall back to the public API.
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        rows = [
            " | ".join(c.text.strip().replace("\n", " ") for c in row.cells)
            for row in table.rows
        ]
        rows = [r for r in rows if r.strip(" |")]
        if rows:
            paragraphs.append("\n".join(rows))
    return paragraphs


def parse_docx(path: str) -> List[Dict[str, Any]]:
    """Extract text from a Word ``.docx`` file, preserving body order."""
    logger.info("Parsing DOCX: %s", path)
    source = os.path.basename(path)

    try:
        blocks = _docx_blocks(path)
    except Exception as exc:
        # Fallback to raw XML extraction from the docx zip. Less faithful (no
        # table structure, no paragraph order guarantees) but it keeps a
        # slightly malformed file usable instead of failing the upload.
        logger.warning("python-docx failed on %s (%s); falling back to XML", path, exc)
        import zipfile
        import xml.etree.ElementTree as ET

        blocks = []
        try:
            with zipfile.ZipFile(path) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            for para in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                text = "".join(node.text or "" for node in para.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                ))
                if text.strip():
                    blocks.append(text.strip())
        except Exception as exc2:
            logger.error("Failed to parse docx %s: %s", path, exc2)
            return []

    return [
        {"text": text, "page": i, "source": source}
        for i, text in enumerate(_paginate_blocks(blocks), start=1)
    ]


def parse_doc(path: str) -> List[Dict[str, Any]]:
    """
    Extract text from a legacy binary Word file (``.doc``, Word 97-2003).

    ``python-docx`` only understands the OOXML zip container, so this format goes
    through :mod:`app.utils.doc_legacy`: a pure-Python OLE2 reader plus the Word
    piece table. No new dependency, which keeps the offline PyInstaller bundle
    working without ``olefile`` or a licensed Word install for COM automation.
    """
    logger.info("Parsing legacy DOC: %s", path)
    source = os.path.basename(path)

    try:
        from app.utils.doc_legacy import doc_to_blocks

        blocks = doc_to_blocks(path)
    except Exception as exc:
        logger.error("Failed to parse legacy doc %s: %s", path, exc)
        return []

    if not blocks:
        logger.warning("No text extracted from legacy doc %s", path)
        return []

    return [
        {"text": text, "page": i, "source": source}
        for i, text in enumerate(_paginate_blocks(blocks), start=1)
    ]


def parse_csv(path: str) -> List[Dict[str, Any]]:
    """
    Extract text from a delimited table (``.csv`` / ``.tsv``).

    A CSV is not prose, so the paragraph pagination used for ``.txt``/``.md``
    would be wrong twice over: it would break rows apart mid-record, and a chunk
    lifted out of the middle of a table loses the header that explains what its
    columns mean. Each pseudo-page therefore holds whole rows and starts with the
    header line, so a retrieved chunk still reads as ``名称 | 价格 | 库存`` rather
    than a row of unexplained values.
    """
    logger.info("Parsing CSV: %s", path)
    source = os.path.basename(path)
    delimiter = "\t" if path.lower().endswith(".tsv") else ","

    content = _read_text_file(path)
    if not content.strip():
        return []

    import csv as _csv
    import io

    try:
        rows = list(_csv.reader(io.StringIO(content), delimiter=delimiter))
    except _csv.Error as exc:
        # Malformed quoting is common in exported files; fall back to the plain
        # text path so the upload still yields searchable content.
        logger.warning("CSV parse failed for %s (%s); treating as plain text", path, exc)
        return parse_text(path)

    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return []

    def render(row: List[str]) -> str:
        return " | ".join(cell.strip() for cell in row)

    header = render(rows[0])
    body = rows[1:]

    # A single-line file is data, not a header plus no rows -- emit it verbatim.
    if not body:
        return [{"text": header, "page": 1, "source": source}]

    # Keep pages near the same 2000-character target as _paginate_blocks, but
    # count whole rows so a record is never split across pages.
    pages: List[str] = []
    current: List[str] = []
    current_len = len(header)

    for row in body:
        line = render(row)
        if current and current_len + len(line) + 1 > 2000:
            pages.append(header + "\n" + "\n".join(current))
            current = []
            current_len = len(header)
        current.append(line)
        current_len += len(line) + 1

    if current:
        pages.append(header + "\n" + "\n".join(current))

    return [
        {"text": text, "page": i, "source": source}
        for i, text in enumerate([p for p in pages if p.strip()], start=1)
    ]


def _pdf_options() -> Dict[str, Any]:
    """Collect the PDF pipeline knobs from settings into keyword arguments."""
    from app.config import get_settings

    s = get_settings()
    return {
        "ocr_enabled": bool(s.enable_ocr_uploads),
        "ocr_engine": s.pdf_ocr_engine,
        "ocr_dpi": s.pdf_ocr_dpi,
        "ocr_max_side": s.pdf_ocr_max_side,
        "ocr_max_pages": s.pdf_ocr_max_pages,
        "ocr_time_budget_seconds": s.pdf_ocr_time_budget_seconds,
        "ocr_min_confidence": s.pdf_ocr_min_confidence,
        "ocr_max_attempts": s.pdf_ocr_max_attempts,
        "ocr_threads": s.pdf_ocr_threads,
        "min_text_chars": s.pdf_min_text_chars,
        "extract_tables": s.pdf_extract_tables,
    }


def parse_pdf_with_audit(
    path: str,
    *,
    progress: Optional[Callable[[str, int, int, str], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parse a PDF and return both the pages and the audit report.

    The heavy lifting lives in :mod:`app.utils.pdf_pipeline`; this wrapper only
    binds it to the settings and logs the outcome. The audit is what lets the
    upload path tell the user "this is a scan, we read 812 of 1439 pages" instead
    of silently ingesting four fragments and letting the model claim it found
    nothing.

    Args:
        progress: Called as ``progress(phase, done, total, detail)``. Phases are
            ``audit``, ``ocr`` and ``finalize``.
    """
    from app.utils.pdf_pipeline import parse_pdf_document

    logger.info("[PDF] Parsing PDF: %s", path)
    pages, audit = parse_pdf_document(path, progress=progress, **_pdf_options())

    logger.info(
        "[PDF] %s: %d page(s) with text, %d OCR'd, %d chars, %d warning(s)",
        os.path.basename(path),
        len(pages),
        audit.get("ocr_pages", 0),
        audit.get("text_chars", 0),
        len(audit.get("warnings") or []),
    )
    return pages, audit


def parse_pdf(
    path: str,
    *,
    progress: Optional[Callable[[str, int, int, str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Parse a PDF into ``{text, page, source}`` records.

    Pages are classified before any OCR runs (see :func:`app.utils.pdf_pipeline.audit_page`):
    a real text layer is used verbatim because it is exact, and OCR is spent only
    on pages that have no usable text -- either a page-sized image with no text
    layer, or one whose "text layer" is a broken remnant of a previous OCR job.
    Preprocessing (deskew, denoise, binarise) escalates only when a page reads
    poorly, since it measurably hurts pages that were already clean.
    """
    pages, _audit = parse_pdf_with_audit(path, progress=progress)
    return pages


def parse_file_with_audit(
    path: str,
    *,
    progress: Optional[Callable[[str, int, int, str], None]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Like :func:`parse_file`, but also returns a parse audit when one applies.

    Only PDF has a layered pipeline worth reporting on; every other format
    returns ``None`` for the audit.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf_with_audit(path, progress=progress)
    return parse_file(path), None


def _extract_text_from_binary_ppt(path: str) -> str:
    """Fallback parser for legacy binary .ppt files (OLE2 format)."""
    text_chunks = []
    try:
        import olefile
        if olefile.isOleFile(path):
            with olefile.OleFileIO(path) as ole:
                if ole.exists('PowerPoint Document'):
                    stream = ole.openstream('PowerPoint Document').read()
                    import re
                    # Extract printable UTF-16LE strings (standard PPT text streams)
                    utf16_matches = re.findall(b'(?:[\x20-\x7e]\x00){3,}', stream)
                    for m in utf16_matches:
                        try:
                            decoded = m.decode('utf-16le', errors='ignore').strip()
                            if len(decoded) > 3 and not decoded.startswith('PowerPoint'):
                                text_chunks.append(decoded)
                        except Exception:
                            pass
                    # Extract ASCII strings
                    ascii_matches = re.findall(b'[\x20-\x7e]{4,}', stream)
                    for m in ascii_matches:
                        try:
                            decoded = m.decode('ascii', errors='ignore').strip()
                            if len(decoded) > 3 and not any(k in decoded for k in ['PowerPoint', 'Current User', 'Document Summary']):
                                text_chunks.append(decoded)
                        except Exception:
                            pass
    except Exception as ole_err:
        logger.warning(f"Olefile extraction notice for {path}: {ole_err}")

    # Fallback to direct raw binary regex string extraction
    if not text_chunks:
        try:
            with open(path, "rb") as f:
                content = f.read()
            import re
            utf16_matches = re.findall(b'(?:[\x20-\x7e]\x00){4,}', content)
            for m in utf16_matches:
                try:
                    decoded = m.decode('utf-16le', errors='ignore').strip()
                    if len(decoded) > 3:
                        text_chunks.append(decoded)
                except Exception:
                    pass
        except Exception as raw_err:
            logger.warning(f"Raw binary extraction failed for {path}: {raw_err}")

    # Deduplicate while preserving order
    seen = set()
    unique_chunks = []
    for c in text_chunks:
        if c not in seen:
            seen.add(c)
            unique_chunks.append(c)

    return "\n".join(unique_chunks)


def parse_pptx(path: str) -> List[Dict[str, Any]]:
    """python-pptx slide-by-slide text extraction with legacy binary .ppt fallback."""
    from pptx import Presentation
    logger.info(f"Parsing PPT/PPTX: {path}")
    source = os.path.basename(path)

    # Strategy 1: OpenXML (.pptx) via python-pptx
    try:
        prs = Presentation(path)
        pages = []
        for i, slide in enumerate(prs.slides):
            text = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
            slide_text = "\n".join(text).strip()
            if slide_text:
                pages.append({
                    "text": slide_text,
                    "page": i + 1,
                    "source": source
                })
        if pages:
            return pages
    except Exception as exc:
        logger.warning(f"python-pptx could not parse {path} as OpenXML: {exc}. Attempting legacy .ppt fallback...")

    # Strategy 2: Legacy binary .ppt format fallback
    full_text = _extract_text_from_binary_ppt(path)
    if not full_text.strip():
        logger.warning(f"No text extracted from PPT file {source}")
        return []

    # Break into pseudo-pages (~2000 chars per page)
    page_size = 2000
    pages = []
    chunks = [full_text[i:i + page_size] for i in range(0, len(full_text), page_size)]
    for i, c in enumerate(chunks, start=1):
        if c.strip():
            pages.append({"text": c.strip(), "page": i, "source": source})
    return pages


_whisper_model_cache = None
_whisper_model_lock = threading.Lock()


def _get_whisper_model():
    """Lazy thread-safe singleton for Faster-Whisper model with CPU fallback handling."""
    global _whisper_model_cache
    if _whisper_model_cache is not None:
        return _whisper_model_cache

    with _whisper_model_lock:
        if _whisper_model_cache is not None:
            return _whisper_model_cache

        from faster_whisper import WhisperModel

        # Shelved capability: whisper_* are no longer part of app.config.Settings,
        # so read them straight from the environment (.env still applies) to keep
        # this parser working if it is ever re-enabled.
        whisper_model = os.environ.get("WHISPER_MODEL", "base")
        whisper_device = os.environ.get("WHISPER_DEVICE", "cpu")

        logger.info(f"[WHISPER] Loading Whisper model ('{whisper_model}') on {whisper_device}...")

        # Temporarily override HF_HUB_OFFLINE so initial model download succeeds on first run
        old_offline = os.environ.pop("HF_HUB_OFFLINE", None)

        model = None
        try:
            for comp_type in ["int8", "default", "float32"]:
                try:
                    logger.info(f"[WHISPER] Attempting load with compute_type='{comp_type}'...")
                    model = WhisperModel(whisper_model, device=whisper_device, compute_type=comp_type)
                    logger.info(f"[WHISPER] Successfully loaded Whisper model with compute_type='{comp_type}'")
                    break
                except Exception as exc:
                    logger.warning(f"[WHISPER] Failed with compute_type='{comp_type}': {exc}")
        finally:
            if old_offline is not None:
                os.environ["HF_HUB_OFFLINE"] = old_offline

        if model is None:
            raise RuntimeError(f"Could not initialize Faster-Whisper model '{whisper_model}'.")

        _whisper_model_cache = model
        return _whisper_model_cache


def _extract_audio_to_wav(media_path: str) -> tuple[str, bool]:
    """
    Extract/normalize any audio or video file into a standard 16kHz mono 16-bit PCM WAV file.
    Returns tuple of (wav_path, is_temp_file).
    """
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    extracted = False

    # Strategy 1: ffmpeg CLI (Fastest & most reliable)
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", media_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            check=True, capture_output=True
        )
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            extracted = True
    except Exception as ffmpeg_err:
        logger.warning(f"[AUDIO] ffmpeg CLI execution failed for {media_path}: {ffmpeg_err}")

    # Strategy 2: PyAV fallback (pure Python bindings)
    if not extracted:
        try:
            import av
            container = av.open(media_path)
            audio_stream = next((s for s in container.streams if s.type == 'audio'), None)
            if audio_stream:
                output_container = av.open(wav_path, 'w', format='wav')
                out_stream = output_container.add_stream('pcm_s16le', rate=16000)
                out_stream.channels = 1

                resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
                for frame in container.decode(audio_stream):
                    for resampled_frame in resampler.resample(frame):
                        for packet in out_stream.encode(resampled_frame):
                            output_container.mux(packet)
                for packet in out_stream.encode(None):
                    output_container.mux(packet)
                output_container.close()
                container.close()
                if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                    extracted = True
        except Exception as av_err:
            logger.warning(f"[AUDIO] PyAV audio extraction failed for {media_path}: {av_err}")

    if extracted:
        return wav_path, True
    else:
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        return media_path, False


def _transcribe_with_whisper(audio_path: str, source: str) -> List[Dict[str, Any]]:
    """Faster-Whisper transcription. Returns segments grouped into ~30-second pseudo-pages."""
    logger.info(f"[WHISPER] Transcribing audio from {source}...")
    try:
        model = _get_whisper_model()
        
        try:
            segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
            segment_list = list(segments)
        except Exception as vad_err:
            logger.warning(f"[WHISPER] Transcribe with vad_filter=True failed for {source} ({vad_err}); retrying with vad_filter=False...")
            segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=False)
            segment_list = list(segments)

        pages = []
        current_text = []
        current_page = 1
        page_duration = 30.0
        start_time = 0.0

        for segment in segment_list:
            text = segment.text.strip()
            if text:
                current_text.append(text)
            if segment.end - start_time >= page_duration:
                joined = " ".join(current_text).strip()
                if joined:
                    pages.append({
                        "text": joined,
                        "page": current_page,
                        "source": source
                    })
                    current_page += 1
                current_text = []
                start_time = segment.end

        if current_text:
            joined = " ".join(current_text).strip()
            if joined:
                pages.append({
                    "text": joined,
                    "page": current_page,
                    "source": source
                })

        logger.info(f"[WHISPER] Transcribed {source}: extracted {len(pages)} pages/chunks from {len(segment_list)} segments")
        return pages
    except Exception as exc:
        logger.exception(f"[WHISPER] Transcription failed for {source}: {exc}")
        return []


def parse_audio(path: str) -> List[Dict[str, Any]]:
    """Extract audio and transcribe with Whisper."""
    source = os.path.basename(path)
    logger.info(f"[AUDIO] Processing audio file: {path}")
    wav_path, is_temp = _extract_audio_to_wav(path)
    try:
        return _transcribe_with_whisper(wav_path, source)
    finally:
        if is_temp and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass


def parse_image(path: str) -> List[Dict[str, Any]]:
    """Extract text from standalone images (PNG, JPG, WEBP, BMP, TIFF) using Tesseract OCR."""
    try:
        from PIL import Image, ImageEnhance
        import pytesseract
    except ImportError:
        logger.error("[IMAGE] pytesseract or PIL is not installed; cannot perform image OCR.")
        return []

    source = os.path.basename(path)
    logger.info(f"[IMAGE] Parsing image with OCR: {path}")

    try:
        image = Image.open(path)
        if image.mode not in ("L", "RGB"):
            image = image.convert("RGB")

        # Contrast enhancement for crisp text OCR
        enhancer = ImageEnhance.Contrast(image)
        enhanced_image = enhancer.enhance(1.4)

        text = pytesseract.image_to_string(enhanced_image, lang="eng", config="--psm 3").strip()
        if not text:
            # Fallback with raw image and PSM 6 (single uniform block of text)
            text = pytesseract.image_to_string(image, lang="eng", config="--psm 6").strip()

        if not text:
            logger.warning(f"[IMAGE] No legible text extracted from {source}")
            return []

        logger.info(f"[IMAGE] Successfully extracted {len(text)} chars from {source}")
        return [{"text": text, "page": 1, "source": source}]
    except Exception as exc:
        logger.exception(f"[IMAGE] Failed to OCR image {source}: {exc}")
        return []


def parse_video(path: str) -> List[Dict[str, Any]]:
    """Extract audio from video file and transcribe with Whisper."""
    source = os.path.basename(path)
    logger.info(f"[VIDEO] Processing video file: {path}")
    wav_path, is_temp = _extract_audio_to_wav(path)
    try:
        return _transcribe_with_whisper(wav_path, source)
    finally:
        if is_temp and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass

