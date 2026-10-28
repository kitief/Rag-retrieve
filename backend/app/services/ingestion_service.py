"""
Document ingestion service.

Pipeline: validate → save temp → parse → chunk → embed → store in ChromaDB → cleanup.

CPU-heavy steps run in a ``ThreadPoolExecutor`` so the event loop stays
responsive. Because parsing a scanned PDF can take minutes, the worker thread
reports progress into :mod:`app.services.progress`, and a small async pump
mirrors that into the ``Document`` row so the UI can follow along.
"""
import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services import progress as progress_registry
from app.utils.chroma_client import add_chunks_to_collection
from app.utils.chunker import chunk_pages
from app.utils.embedder import embed_texts
from app.core.i18n import t
from app.utils.parsers import is_extension_allowed, parse_file_with_audit

logger = logging.getLogger(__name__)

# One shared executor for CPU-bound work (parsing + embedding). Kept small on
# purpose: OCR already saturates every core it can get, so a second concurrent
# OCR job would not finish sooner -- it would just make both jobs slower.
_executor = ThreadPoolExecutor(max_workers=2)

#: How often the pump copies in-memory progress into the database.
_PUMP_INTERVAL_SECONDS = 0.4

#: Share of a document that may go unread before ingestion refuses it outright.
#: Below this the audit badge is enough of a warning; above it the document would
#: be mostly unanswerable, and "ready" would be a lie.
_UNREAD_TOLERANCE = 0.5


def _validate_extension(filename: str) -> str:
    """Return the lowercased extension or raise ValueError for unsupported types."""
    ext = os.path.splitext(filename)[1].lower()
    if not is_extension_allowed(ext):
        raise ValueError(t("doc.unsupported_type", ext=ext))
    return ext


def _sync_ingest_pipeline(
    file_path: str,
    filename: str,
    chat_id: str,
    document_id: str,
    chunk_size: int,
    chunk_overlap: int,
    reporter: Optional[progress_registry.ProgressReporter] = None,
) -> dict:
    """
    Synchronous ingestion steps (run in a thread pool):

      1. Parse file → list of pages (plus a parse audit for PDFs)
      2. Chunk pages → list of chunks
      3. Embed chunks → list of vectors
      4. Upsert into ChromaDB

    Returns ``{total_pages, total_chunks, audit}``. ``audit`` is ``None`` for
    formats that have no layered pipeline.
    """
    def report(percent: int, stage: str, detail: str = "") -> None:
        if reporter is not None:
            reporter.update(percent, stage, detail)

    report(progress_registry.PARSE_START, "parse", filename)
    logger.info("[INGEST] Parsing %s (document_id=%s)", filename, document_id)

    def parse_progress(phase: str, done: int, total: int, detail: str = "") -> None:
        """
        Map the PDF pipeline's own phases onto the parse slice of the bar.

        Auditing is cheap (a 1400-page book audits in under a second), so it
        gets the first tenth of the slice; OCR is where the minutes go, so it
        owns everything after that.
        """
        span = progress_registry.PARSE_END - progress_registry.PARSE_START
        if total <= 0:
            fraction = 0.0
        elif phase == "audit":
            fraction = 0.10 * (done / total)
        elif phase == "ocr":
            fraction = 0.10 + 0.90 * (done / total)
        else:
            fraction = 1.0
        report(
            progress_registry.PARSE_START + int(span * fraction),
            phase,
            f"{done}/{total}" + (f" · {detail}" if detail else ""),
        )

    pages, audit = parse_file_with_audit(file_path, progress=parse_progress)

    # A PDF whose pages are scans did not "contain no text" -- the text was never
    # read. Indexing the leftovers and reporting "ready" is exactly the failure
    # that made the user's book unanswerable, so it is refused with a reason.
    _ensure_usable_text(pages, audit)

    # The pipeline reports the real filename; make sure the chunk metadata uses
    # it too (the temp file has a UUID name).
    for p in pages:
        p["source"] = filename

    # Same for the audit: it is built from the temp path, and a UUID is not what
    # the reader of the audit dialog wants to see.
    if audit:
        audit["filename"] = filename

    total_pages = len(pages)
    logger.info("[INGEST] Extracted %d pages from %s", total_pages, filename)
    if audit and audit.get("warnings"):
        for warning in audit["warnings"]:
            logger.warning("[INGEST] %s: %s", filename, warning)

    report(progress_registry.CHUNK_AT, "chunk", f"{total_pages} pages")
    chunks = chunk_pages(pages, chunk_size=chunk_size, overlap=chunk_overlap)
    total_chunks = len(chunks)
    logger.info("[INGEST] Created %d chunks from %s", total_chunks, filename)

    if chunks:
        texts = [c["text"] for c in chunks]
        report(progress_registry.EMBED_START, "embed", f"0/{total_chunks}")
        logger.info("[INGEST] Embedding %d chunks...", total_chunks)

        def embed_progress(done: int, total: int) -> None:
            span = progress_registry.EMBED_END - progress_registry.EMBED_START
            report(
                progress_registry.EMBED_START + int(span * (done / max(1, total))),
                "embed",
                f"{done}/{total}",
            )

        embeddings = embed_texts(texts, progress=embed_progress)

        report(progress_registry.STORE_AT, "store", f"{total_chunks} chunks")
        logger.info("[INGEST] Storing chunks in ChromaDB collection chat_%s", chat_id)
        add_chunks_to_collection(chat_id, chunks, embeddings, document_id)

    report(progress_registry.DONE, "done", f"{total_chunks} chunks")
    return {"total_pages": total_pages, "total_chunks": total_chunks, "audit": audit}


async def _pump_progress(document_id: str, reporter: progress_registry.ProgressReporter) -> None:
    """
    Copy in-memory progress into the ``documents`` row while parsing runs.

    Uses its own short-lived session so it never competes with the request's
    session, and swallows its own errors: progress is a convenience, and a
    failed write here must never fail an ingestion.
    """
    from app.database import AsyncSessionLocal

    last: Optional[tuple] = None
    while True:
        await asyncio.sleep(_PUMP_INTERVAL_SECONDS)
        snap = reporter.snapshot()
        current = (snap["progress"], snap["stage"])
        if current == last:
            continue
        last = current
        try:
            async with AsyncSessionLocal() as session:
                row = await session.get(Document, UUID(document_id))
                if row is None:
                    return
                row.progress = snap["progress"]
                row.progress_stage = snap["stage"]
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[INGEST] progress pump write failed: %s", exc)


async def _stop_pump(pump: "asyncio.Task") -> None:
    """
    Cancel the progress pump and wait for it to actually stop.

    Waiting matters: ``cancel()`` only requests cancellation, so a tick that is
    already mid-write would still commit. Without the await, a 97% tick could
    land *after* the final "100% / done" commit and leave the bar stuck at 97%
    forever.
    """
    pump.cancel()
    try:
        await pump
    except asyncio.CancelledError:
        pass
    except Exception:  # pragma: no cover - defensive
        logger.debug("[INGEST] progress pump ended with an error", exc_info=True)


def _ensure_usable_text(pages: list[dict], audit: dict | None) -> None:
    """
    Refuse an ingestion whose pages were never actually read.

    A scanned PDF whose OCR is switched off still yields *something* -- the odd
    page with a partial text layer -- so a naive "did we get any text?" check
    passes while 5 of 7 pages are missing. The book then shows a green "ready"
    badge and answers "not found" for most questions, which reads as a broken
    product rather than a disabled feature.

    Two situations are refused rather than half-indexed:

    * the machine has no OCR engine at all;
    * pages needed OCR and it did not run (disabled, or refused to start).

    A fully OCR'd document (``ocr_pages > 0``), a genuinely blank PDF, and a
    mostly-digital document with the odd scanned appendix are all left alone --
    a couple of unread pages out of two hundred is a warning, not a failure.
    """
    if not audit:
        return
    scanned = audit.get("scanned_pages") or 0
    if scanned <= 0:
        return
    if (audit.get("ocr_pages") or 0) > 0:
        return

    total = audit.get("total_pages") or scanned
    unread = audit.get("ocr_skipped_pages") or scanned
    # A handful of scanned pages inside an otherwise readable document is what
    # the audit badge is for; losing most of the document is a different thing.
    if pages and (unread / max(total, 1)) <= _UNREAD_TOLERANCE:
        return

    if not audit.get("ocr_available", True):
        raise RuntimeError(
            "This PDF is a scan and no OCR engine is installed, so its text "
            "could not be read. Install rapidocr-onnxruntime, then upload it again."
        )
    raise RuntimeError(
        f"This PDF is a scan: {unread} of {total} page(s) could not be read "
        "without OCR. Set ENABLE_OCR_UPLOADS=true and upload it again."
    )


def _failure_reason(exc: Exception) -> str:
    """
    Turn an ingestion exception into something worth showing a user.

    Our own ``RuntimeError`` messages already explain the situation ("this PDF
    is a scan and OCR is off"), so they pass through. Everything else is opaque
    -- a stack frame or a driver error -- and is summarised instead.
    """
    text = str(exc).strip()
    if isinstance(exc, RuntimeError) and text and not text.startswith("Document record"):
        return text[:500]
    if isinstance(exc, ValueError):
        return text[:500] or "The file could not be parsed."
    return f"Ingestion failed: {text[:400]}" if text else "Ingestion failed."


async def ingest_document(
    db: AsyncSession,
    chat_id: str,
    file_path: str,
    filename: str,
    document_id: str,
) -> Document:
    """
    Full asynchronous ingestion pipeline.

    1. Validate file extension (reject unsupported types like images, etc.)
    2. Run CPU-heavy parse → chunk → embed → store in a thread pool
    3. Update the Document row with results, progress and the parse audit
    4. Delete the temporary file
    5. Return the updated Document record

    On any failure: set status='failed', delete temp file, re-raise.
    """
    from app.config import get_settings

    cfg = get_settings()

    # ── Step 1: Validate extension ────────────────────────────────────────────
    try:
        _validate_extension(filename)
    except ValueError as exc:
        logger.error("[INGEST] Rejected file %s: %s", filename, exc)
        raise

    # ── Step 2: Fetch the Document record ─────────────────────────────────────
    result = await db.execute(
        select(Document).where(Document.id == UUID(document_id))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise RuntimeError(f"Document record not found: {document_id}")

    doc.progress = 0
    doc.progress_stage = "queued"
    await db.commit()

    reporter = progress_registry.start(document_id)
    pump = asyncio.create_task(_pump_progress(document_id, reporter))

    try:
        # ── Step 3: Run pipeline in thread pool ───────────────────────────────
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(
            _executor,
            _sync_ingest_pipeline,
            file_path,
            filename,
            chat_id,
            document_id,
            cfg.chunk_size,
            cfg.chunk_overlap,
            reporter,
        )

        # ── Step 4: Update DB record ──────────────────────────────────────────
        # Stop the pump first, so nothing it has in flight can overwrite the
        # final values written below.
        await _stop_pump(pump)
        doc.total_pages = stats["total_pages"]
        doc.total_chunks = stats["total_chunks"]
        doc.status = "processed"
        doc.progress = 100
        doc.progress_stage = "done"
        audit = stats.get("audit")
        doc.parse_audit = json.dumps(audit, ensure_ascii=False) if audit else None
        doc.error_message = None
        await db.commit()
        await db.refresh(doc)
        logger.info(
            "[INGEST] Completed %s: %d pages, %d chunks",
            filename,
            stats["total_pages"],
            stats["total_chunks"],
        )

    except Exception as exc:
        logger.exception("[INGEST] Failed to ingest %s: %s", filename, exc)
        await _stop_pump(pump)
        doc.status = "failed"
        doc.progress_stage = "failed"
        # Surface the reason in the UI: "failed" alone does not tell a user that
        # the file is a scan and OCR is switched off.
        doc.error_message = _failure_reason(exc)
        await db.commit()
        raise

    finally:
        await _stop_pump(pump)
        progress_registry.finish(document_id)
        # ── Step 5: Delete the temp file (always) ────────────────────────────
        if os.path.exists(file_path):
            os.unlink(file_path)
            logger.debug("[INGEST] Deleted temp file: %s", file_path)

    return doc
