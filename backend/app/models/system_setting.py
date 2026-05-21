"""System-wide dynamic settings stored in the database."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from app.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(255), primary_key=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SystemSetting {self.key}>"
