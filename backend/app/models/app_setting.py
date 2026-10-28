from sqlalchemy import Column, String, DateTime, Text
import uuid
from datetime import datetime
from app.database import Base


class AppSetting(Base):
    """
    Simple key/value store for settings edited from the web UI.

    Only non-secret or secret-but-required values live here (the LLM API key is
    the one exception, and it is never returned to the browser in clear text).
    Built-in defaults come from environment variables; these rows act as a
    runtime override so a user can point the app at another provider without
    editing files.
    """

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


__all__ = ["AppSetting"]
