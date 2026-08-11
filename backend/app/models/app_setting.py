from sqlalchemy import Column, String
from app.core.database import Base


class AppSetting(Base):
    """Runtime-togglable app settings (key/value), editable from the UI."""
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(256), nullable=False)
