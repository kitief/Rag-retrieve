from sqlalchemy import Column, String, DateTime
from sqlalchemy import Uuid
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    chats = relationship("Chat", back_populates="user")
    memories = relationship("UserMemory", back_populates="user")
