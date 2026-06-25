"""Service for managing dynamic system settings stored in the database."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)


class SettingService:
    """Load and save dynamic system settings, syncing them to the global config."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key."""
        result = await self.db.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else default

    async def set(self, key: str, value: str) -> SystemSetting:
        """Set a setting value, creating the row if it doesn't exist."""
        result = await self.db.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = result.scalar_one_or_none()

        if row:
            row.value = value
        else:
            row = SystemSetting(key=key, value=value)
            self.db.add(row)

        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def load_into_config(self) -> None:
        """Load all persisted settings and apply them to the global settings object."""
        result = await self.db.execute(select(SystemSetting))
        rows = result.scalars().all()

        for row in rows:
            if row.key == "maintenance_mode":
                settings.maintenance_mode = row.value.lower() == "true"
                logger.info(f"Loaded maintenance_mode={settings.maintenance_mode} from DB")
            elif row.key == "maintenance_message":
                settings.maintenance_message = row.value
                logger.info("Loaded maintenance_message from DB")
            elif row.key == "daily_allowance_default":
                try:
                    settings.daily_allowance_default = int(row.value)
                except ValueError:
                    logger.warning(f"Invalid daily_allowance_default value: {row.value}")

    async def save_maintenance(self, enabled: bool, message: str | None = None) -> None:
        """Persist maintenance mode settings to the database and update global config."""
        await self.set("maintenance_mode", "true" if enabled else "false")
        if message is not None:
            await self.set("maintenance_message", message)

        settings.maintenance_mode = enabled
        if message is not None:
            settings.maintenance_message = message

    async def get_maintenance(self) -> dict:
        """Get current maintenance mode settings (from DB or fallback to config)."""
        mode_str = await self.get("maintenance_mode")
        msg = await self.get("maintenance_message")

        return {
            "maintenance_mode": (mode_str.lower() == "true")
            if mode_str is not None
            else settings.maintenance_mode,
            "maintenance_message": msg if msg is not None else settings.maintenance_message,
        }
