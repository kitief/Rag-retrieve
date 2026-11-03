"""
Notes router: API endpoints for AI Notes generation and retrieval.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.dependencies import get_current_user, get_db, get_owned_chat
from app.models.user import User
from app.schemas.note import NotesResponse
from app.services.notes_service import (
    build_notes_pdf,
    build_remedial_notes_pdf,
    generate_notes,
    generate_remedial_quiz_notes,
    get_latest_notes,
    get_latest_remedial_notes,
)
from app.services.document_readiness import ensure_documents_ready

router = APIRouter(prefix="/chats", tags=["Notes"])


@router.post("/{chat_id}/notes", response_model=NotesResponse, status_code=201)
async def create_notes(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotesResponse:
    """Generate structured AI note cards for all resources in a knowledge space."""
    await get_owned_chat(chat_id, current_user, db)
    await ensure_documents_ready(chat_id, db)
    note = await generate_notes(db=db, chat_id=chat_id)
    return NotesResponse.model_validate(note)


@router.get("/{chat_id}/notes", response_model=Optional[NotesResponse])
async def fetch_notes(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[NotesResponse]:
    """Get the latest AI note cards for a knowledge space. Returns null if none generated yet."""
    await get_owned_chat(chat_id, current_user, db)
    note = await get_latest_notes(db=db, chat_id=chat_id)
    if not note:
        return None
    return NotesResponse.model_validate(note)


@router.get("/{chat_id}/notes/pdf")
async def download_notes_pdf(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the latest complete page-by-page notes as a searchable PDF."""
    await get_owned_chat(chat_id, current_user, db)
    note = await get_latest_notes(db=db, chat_id=chat_id)
    if not note:
        raise HTTPException(status_code=404, detail=t("notes.notes_required"))
    return Response(
        content=await asyncio.to_thread(build_notes_pdf, note),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ragvault-notes-{chat_id}.pdf"'},
    )


@router.post("/{chat_id}/quiz-remedial-notes", response_model=NotesResponse, status_code=201)
async def create_remedial_notes(
    chat_id: str,
    quiz_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotesResponse:
    """Generate targeted remedial study cards for missed questions from a submitted quiz."""
    await get_owned_chat(chat_id, current_user, db)
    note = await generate_remedial_quiz_notes(db=db, chat_id=chat_id, quiz_id=quiz_id)
    return NotesResponse.model_validate(note)


@router.get("/{chat_id}/quiz-remedial-notes", response_model=Optional[NotesResponse])
async def fetch_remedial_notes(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[NotesResponse]:
    """Fetch the latest generated quiz remedial notes."""
    await get_owned_chat(chat_id, current_user, db)
    note = await get_latest_remedial_notes(db=db, chat_id=chat_id)
    if not note:
        return None
    return NotesResponse.model_validate(note)


@router.get("/{chat_id}/quiz-remedial-notes/pdf")
async def download_remedial_notes_pdf(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the targeted quiz wrong-answers remedial notes as a PDF."""
    await get_owned_chat(chat_id, current_user, db)
    note = await get_latest_remedial_notes(db=db, chat_id=chat_id)
    if not note:
        raise HTTPException(status_code=404, detail=t("notes.remedial_required"))
    return Response(
        content=await asyncio.to_thread(build_remedial_notes_pdf, note),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ragvault-quiz-remedial-{chat_id}.pdf"'},
    )
