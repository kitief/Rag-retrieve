from pydantic import BaseModel, field_validator
from datetime import datetime
import json
from uuid import UUID
from typing import Any, Dict, List, Optional


class DocumentResponse(BaseModel):
    id: UUID
    chat_id: UUID
    filename: str
    file_type: str
    upload_time: datetime
    total_pages: Optional[int] = None
    total_chunks: Optional[int] = None
    status: str

    # ── Ingestion progress ────────────────────────────────────────────────────
    # Present so the UI can show "OCR page 412/1439" instead of an unchanging
    # spinner. ``progress_stage`` is the pipeline phase that produced the value.
    progress: Optional[int] = None
    progress_stage: Optional[str] = None

    # ── Parse audit ───────────────────────────────────────────────────────────
    # The layered PDF pipeline stores a JSON report per document (page kinds,
    # OCR confidences, skipped pages, warnings). It is exposed as a nested object
    # rather than a raw string so the client does not have to double-parse it.
    parse_audit: Optional[Dict[str, Any]] = None

    # ── Failure reason ────────────────────────────────────────────────────────
    # Filled only when ``status == "failed"``. Without it the UI can only show a
    # red badge, which does not tell the user that their PDF is a scan and OCR is
    # switched off.
    error_message: Optional[str] = None

    @field_validator("parse_audit", mode="before")
    @classmethod
    def _decode_audit(cls, value: Any) -> Any:
        """Accept the stored JSON text and hand back a dict (or None)."""
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                # A corrupt audit must not make the whole document unreadable.
                return None
            return decoded if isinstance(decoded, dict) else None
        return None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
