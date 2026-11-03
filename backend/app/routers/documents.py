"""
Documents router: file upload, status polling, and deletion.
PDF, PPTX/PPT, DOCX/DOC, Markdown, TXT and CSV/TSV files are accepted — everything
else is rejected with 422.
Ingestion runs as a FastAPI BackgroundTask to avoid blocking the HTTP response.
"""
import asyncio
import logging
import os
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.dependencies import get_current_user, get_db, get_owned_chat, to_uuid
from app.database import AsyncSessionLocal
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.ingestion_service import _validate_extension, ingest_document
from app.utils.chroma_client import delete_document_chunks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["Documents"])

def _max_upload_bytes() -> int:
    from app.config import get_settings

    return get_settings().max_upload_bytes


def _format_size(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):g} MB"


async def _background_ingest(
    chat_id: str,
    file_path: str,
    filename: str,
    document_id: str,
) -> None:
    """
    Background task entry point.

    Reuses the global ``AsyncSessionLocal`` (and its shared engine/PRAGMA
    setup) instead of building a second engine per upload, so ingestion goes
    through the same connection pool as every other database path.
    """
    async with AsyncSessionLocal() as session:
        try:
            await ingest_document(
                db=session,
                chat_id=chat_id,
                file_path=file_path,
                filename=filename,
                document_id=document_id,
            )
        except Exception as exc:
            logger.exception("[INGEST:BG] Background ingestion failed for %s (%s): %s", filename, document_id, exc)


@router.post(
    "/{chat_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    chat_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Upload and ingest a document into a knowledge space.

    - Validates file type (PDF, PPTX/PPT, DOCX/DOC, Markdown, TXT, CSV/TSV).
    - Streams file to temporary storage.
    - Creates Document record in 'processing' status.
    - Dispatches ingestion pipeline as a background task.
    - Returns 202 Accepted immediately with the Document record.
    """
    await get_owned_chat(chat_id, current_user, db)

    # Validate file extension
    try:
        ext = _validate_extension(file.filename or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    from app.config import get_settings
    cfg = get_settings()

    # Save to temp directory
    doc_id = uuid4()
    temp_filename = f"{doc_id}{ext}"
    os.makedirs(cfg.upload_temp_dir, exist_ok=True)
    temp_path = os.path.join(cfg.upload_temp_dir, temp_filename)

    file_size = 0
    max_bytes = _max_upload_bytes()
    async with aiofiles.open(temp_path, "wb") as out_file:
        while content := await file.read(1024 * 1024):  # 1MB chunks
            file_size += len(content)
            if file_size > max_bytes:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=t("doc.too_large", size=_format_size(max_bytes)),
                )
            await out_file.write(content)

    cid = to_uuid(chat_id)
    # Create Document record in DB
    doc = Document(
        id=doc_id,
        chat_id=cid,
        filename=file.filename,
        file_type=ext.lstrip("."),
        chroma_collection=f"chat_{str(cid).replace('-', '_')}",
        status="processing",
        total_pages=0,
        total_chunks=0,
        # Seed the progress columns so the row is self-describing from the first
        # response: without this the client sees a bare "processing" until the
        # background task happens to write its first tick.
        progress=0,
        progress_stage="queued",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Launch background ingestion
    background_tasks.add_task(
        _background_ingest,
        chat_id=chat_id,
        file_path=temp_path,
        filename=file.filename,
        document_id=str(doc_id),
    )

    return DocumentResponse.model_validate(doc)


@router.get("/{chat_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List all documents in a knowledge space with their processing status."""
    await get_owned_chat(chat_id, current_user, db)
    cid = to_uuid(chat_id)
    result = await db.execute(
        select(Document).where(Document.chat_id == cid).order_by(Document.upload_time.desc())
    )
    docs = result.scalars().all()
    return DocumentListResponse(documents=[DocumentResponse.model_validate(d) for d in docs])


@router.delete("/{chat_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    chat_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document and remove its chunks from ChromaDB."""
    await get_owned_chat(chat_id, current_user, db)
    cid = to_uuid(chat_id)
    doc_uuid = to_uuid(doc_id)

    result = await db.execute(
        select(Document).where(Document.id == doc_uuid, Document.chat_id == cid)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=t("doc.not_found"))

    await asyncio.to_thread(delete_document_chunks, chat_id, doc_id)
    await db.delete(doc)
    await db.commit()
