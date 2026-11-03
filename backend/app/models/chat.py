from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from app.database import Base

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="chat", cascade="all, delete-orphan")
    quizzes = relationship("Quiz", back_populates="chat", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="chat", cascade="all, delete-orphan")
    memories = relationship("UserMemory", back_populates="source_chat", cascade="all, delete-orphan")
