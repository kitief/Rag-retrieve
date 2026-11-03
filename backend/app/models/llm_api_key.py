"""
Saved LLM API keys.

The settings dialog lets a user keep several keys around (for example one per
provider, or a personal and a team key) and switch between them without
retyping. The *active* key still lives in ``app_settings.llm_api_key`` so the hot
path in :mod:`app.services.llm_client` stays a single dict lookup; this table is
only the vault of the alternatives.

Values are stored in clear text, exactly like the active key in ``app_settings``.
This is a self-hosted deployment: the database is the trust boundary, and the
API never returns a stored key — only a masked hint.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text

from app.database import Base


class LLMApiKey(Base):
    """One saved API key for a provider."""

    __tablename__ = "llm_api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String, nullable=False, default="custom")
    label = Column(String, nullable=False, default="")
    value = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


__all__ = ["LLMApiKey"]
