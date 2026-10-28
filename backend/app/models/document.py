from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
from sqlalchemy import CheckConstraint
import uuid
from datetime import datetime
from app.database import Base

class Document(Base):
    __tablename__ = "documents"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    upload_time = Column(DateTime, default=datetime.utcnow)
    total_pages = Column(Integer, nullable=True)
    total_chunks = Column(Integer, nullable=True)
    chroma_collection = Column(String, nullable=False)
    status = Column(String, nullable=False)

    # ── Ingestion progress ────────────────────────────────────────────────────
    # Parsing a scanned PDF can take minutes, and a spinner that never changes is
    # indistinguishable from a hang. ``progress`` is 0-100 over the whole
    # pipeline; ``progress_stage`` names the phase ("audit", "ocr", "embed", …)
    # so the UI can say what is actually happening.
    progress = Column(Integer, nullable=True)
    progress_stage = Column(String, nullable=True)

    # ── Parse audit ───────────────────────────────────────────────────────────
    # JSON document produced by the layered PDF pipeline: per-page verdicts, OCR
    # confidences, skipped pages and warnings. Stored as text rather than a JSON
    # column because SQLite's type affinity would otherwise try to coerce the
    # string. Keeping it makes "why did this document ingest as four fragments?"
    # answerable after the fact instead of only in the log.
    parse_audit = Column(Text, nullable=True)

    # ── Failure reason ────────────────────────────────────────────────────────
    # A red "failed" badge with no reason is only marginally better than the
    # silent success this used to be. The message is user-facing (it says "this
    # PDF is a scan, OCR is off"), so it is stored rather than logged.
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(status.in_(['processing', 'processed', 'failed']), name='status_check'),
    )

    chat = relationship("Chat", back_populates="documents")
