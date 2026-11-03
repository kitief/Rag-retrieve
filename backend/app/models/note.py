from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from app.database import Base

class Note(Base):
    __tablename__ = "notes"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    title = Column(String, nullable=False)
    cards = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    chat = relationship("Chat", back_populates="notes")
