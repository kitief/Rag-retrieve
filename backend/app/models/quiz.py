from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from app.database import Base

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    topic = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    total_questions = Column(Integer, nullable=False)
    weak_topics = Column(JSON, nullable=True)
    questions = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    chat = relationship("Chat", back_populates="quizzes")
