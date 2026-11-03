from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
from sqlalchemy import CheckConstraint
import uuid
from datetime import datetime, timezone
from app.database import Base

class Message(Base):
    __tablename__ = "messages"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint(role.in_(['user', 'assistant']), name='role_check'),
    )

    chat = relationship("Chat", back_populates="messages")
