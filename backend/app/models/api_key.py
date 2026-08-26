from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class ApiKey(Base):
    """Panel API keys. Hash is used for lookup; plaintext is kept for copy."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True)
    key_prefix = Column(String(16), nullable=False)
    key_plain = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
