# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

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
            elif row.key in ("credits_daily_allowance", "daily_allowance_default"):
                try:
                    settings.credits_daily_allowance = int(row.value)
                except ValueError:
                    logger.warning(f"Invalid credits_daily_allowance value: {row.value}")
            elif row.key == "credits_max_balance":
                try:
                    settings.credits_max_balance = int(row.value)
                except ValueError:
                    logger.warning(f"Invalid credits_max_balance value: {row.value}")

    async def save_maintenance(self, enabled: bool, message: str | None = None) -> None:
        """Persist maintenance mode settings to the database and update global config."""
        await self.set("maintenance_mode", "true" if enabled else "false")
        if message is not None:
            await self.set("maintenance_message", message)

        settings.maintenance_mode = enabled
        if message is not None:
            settings.maintenance_message = message

    async def get_daily_allowance(self) -> int:
        """Return the system-wide default daily allowance.

        Always reads from the database (with a fallback to the in-process
        config default) so values written by other worker processes are
        observed without requiring a restart.
        """
        for key in ("credits_daily_allowance", "daily_allowance_default"):
            value = await self.get(key)
            if value is not None:
                try:
                    return int(value)
                except ValueError:
                    logger.warning(f"Invalid {key} value: {value}")
        return settings.credits_daily_allowance

    async def set_daily_allowance(self, amount: int) -> None:
        """Persist the system-wide default daily allowance and refresh config."""
        await self.set("credits_daily_allowance", str(amount))
        settings.credits_daily_allowance = amount

    async def get_max_balance(self) -> int:
        """Return the system-wide credit balance cap.

        0 means unlimited. Always reads from the database (with a
        fallback to the in-process config default) so changes made by
        other worker processes are observed without requiring a restart.
        """
        value = await self.get("credits_max_balance")
        if value is not None:
            try:
                return int(value)
            except ValueError:
                logger.warning(f"Invalid credits_max_balance value: {value}")
        return settings.credits_max_balance

    async def set_max_balance(self, amount: int) -> None:
        """Persist the system-wide credit balance cap and refresh config.

        Pass 0 to disable the cap (unlimited).
        """
        await self.set("credits_max_balance", str(amount))
        settings.credits_max_balance = amount

    async def get_quota_defaults(self) -> dict[str, float | int | str]:
        """Return system-wide default resource quota limits.

        Reads from the database and falls back to the in-process config
        defaults so values written by other workers are observed.
        """
        defaults = {
            "max_cpu_total": 8.0,
            "max_memory_total": "16g",
            "max_disk_total": "100g",
            "max_gpu_total": 0,
            "max_servers_total": 5,
        }
        for key in defaults:
            value = await self.get(f"quota_default_{key}")
            if value is None:
                continue
            if key in ("max_cpu_total",):
                try:
                    defaults[key] = float(value)
                except ValueError:
                    logger.warning(f"Invalid {key} value: {value}")
            elif key in ("max_gpu_total", "max_servers_total"):
                try:
                    defaults[key] = int(value)
                except ValueError:
                    logger.warning(f"Invalid {key} value: {value}")
            else:
                defaults[key] = value
        return defaults

    async def set_quota_defaults(self, defaults: dict[str, float | int | str]) -> None:
        """Persist system-wide default resource quota limits."""
        valid_keys = {
            "max_cpu_total",
            "max_memory_total",
            "max_disk_total",
            "max_gpu_total",
            "max_servers_total",
        }
        for key, value in defaults.items():
            if key not in valid_keys:
                continue
            await self.set(f"quota_default_{key}", str(value))

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
