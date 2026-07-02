# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Service for managing data retention policies."""

import contextlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.retention import DEFAULT_RETENTION_POLICIES, VALIDATION_RANGES
from app.models.system_setting import SystemSetting


class RetentionService:
    """Manage retention policies stored in SystemSetting."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_policy(self) -> dict[str, Any]:
        """Get current retention policy from DB, filling in defaults."""
        policy = dict(DEFAULT_RETENTION_POLICIES)

        result = await self.db.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_(list(DEFAULT_RETENTION_POLICIES.keys()))
            )
        )
        rows = result.scalars().all()

        for row in rows:
            if row.key in policy:
                if isinstance(policy[row.key], bool):
                    policy[row.key] = row.value.lower() == "true" if row.value else policy[row.key]
                elif isinstance(policy[row.key], int):
                    with contextlib.suppress(ValueError, TypeError):
                        policy[row.key] = int(row.value)

        return policy

    async def set_policy(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Update retention policy settings with validation."""
        validated = {}

        for key, value in updates.items():
            if key not in DEFAULT_RETENTION_POLICIES:
                raise ValueError(f"Unknown retention setting: {key}")

            # Convert to correct type
            default = DEFAULT_RETENTION_POLICIES[key]
            if isinstance(default, bool):
                value = value.lower() == "true" if isinstance(value, str) else bool(value)
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    raise ValueError(f"Invalid integer value for {key}: {value}")

            # Validate range
            if key in VALIDATION_RANGES:
                min_val, max_val = VALIDATION_RANGES[key]
                if not (min_val <= value <= max_val):
                    raise ValueError(f"{key} must be between {min_val} and {max_val}")

            validated[key] = value

        # Persist to DB
        for key, value in validated.items():
            result = await self.db.execute(select(SystemSetting).where(SystemSetting.key == key))
            row = result.scalar_one_or_none()

            str_value = str(value)
            if row:
                row.value = str_value
            else:
                row = SystemSetting(key=key, value=str_value)
                self.db.add(row)

        await self.db.commit()

        return await self.get_policy()
