# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""System-wide dynamic settings stored in the database."""

from sqlalchemy import Column, DateTime, String, Text

from app.core.time_utils import utc_now
from app.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(255), primary_key=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<SystemSetting {self.key}>"
