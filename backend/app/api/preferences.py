# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Preferences API endpoints.
"""

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import UserService

router = APIRouter()


class PreferencesUpdateRequest(BaseModel):
    theme: str | None = Field(
        None,
        description="Theme: default, graphite, ocean, amber, github, nord, everforest, rosepine",
    )
    accent_color: str | None = Field(None, description="Custom accent color (OKLCH value)")
    oled_mode: bool | None = Field(None, description="OLED dark mode")
    use_gravatar: bool | None = Field(None, description="Use Gravatar for profile image")
    language: str | None = Field(None, description="Language code")
    timezone: str | None = Field(None, description="Timezone")
    default_environment: str | None = Field(None, description="Default environment")
    default_plan: str | None = Field(None, description="Default plan")
    notifications: dict | None = Field(None, description="Notification preferences")
    dashboard: dict | None = Field(None, description="Dashboard preferences")
    sidebar_collapsed: bool | None = Field(None, description="Sidebar collapsed state")
    sidebar_pinned: bool | None = Field(None, description="Sidebar pinned state")
    density: str | None = Field(None, description="UI density: compact, comfortable")
    pinned_workspace_ids: list | None = Field(None, description="List of pinned workspace IDs")
    idle_shutdown_enabled: bool | None = Field(None, description="Auto-stop idle servers")
    idle_shutdown_timeout: int | None = Field(
        None, description="Minutes of inactivity before shutdown (5-240)"
    )
    stop_on_logout: bool | None = Field(None, description="Stop all servers on explicit logout")


class PreferencesResponse(BaseModel):
    theme: str
    accent_color: str | None
    oled_mode: bool
    use_gravatar: bool
    language: str
    timezone: str
    default_environment: str
    default_plan: str
    notifications: dict
    dashboard: dict
    sidebar_collapsed: bool
    sidebar_pinned: bool
    density: str
    pinned_workspace_ids: list
    idle_shutdown_enabled: bool
    idle_shutdown_timeout: int
    stop_on_logout: bool


def get_default_preferences() -> dict:
    """Get default preferences"""
    return {
        "theme": "default",
        "accent_color": None,
        "oled_mode": False,
        "use_gravatar": True,
        "language": "en",
        "timezone": "UTC",
        "default_environment": "dev",
        "default_plan": "small",
        "sidebar_collapsed": False,
        "sidebar_pinned": True,
        "density": "comfortable",
        "pinned_workspace_ids": [],
        "notifications": {
            "email": {
                "server_events": True,
                "credit_low": True,
                "security_alerts": True,
            },
            "web": {
                "server_events": True,
                "credit_low": True,
                "security_alerts": True,
                "system_updates": True,
            },
        },
        "dashboard": {
            "default_view": "grid",
            "show_inactive_servers": False,
            "auto_refresh_interval": 30,
            "metrics_time_range": "1h",
        },
        "idle_shutdown_enabled": True,
        "idle_shutdown_timeout": 15,
        "stop_on_logout": False,
    }


@router.get("/")
async def get_preferences(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Get current user's preferences"""
    prefs = current_user.preferences or {}

    # Merge with defaults
    defaults = get_default_preferences()
    merged = {**defaults, **prefs}

    return merged


@router.put("/")
async def update_preferences(
    request: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's preferences"""
    service = UserService(db)

    # Get current preferences
    current_prefs = current_user.preferences or {}

    # Update with new values (only provided fields)
    update_data = {}
    if request.theme is not None:
        update_data["theme"] = request.theme
    if request.accent_color is not None:
        update_data["accent_color"] = request.accent_color
    if request.oled_mode is not None:
        update_data["oled_mode"] = request.oled_mode
    if request.language is not None:
        update_data["language"] = request.language
    if request.timezone is not None:
        update_data["timezone"] = request.timezone
    if request.default_environment is not None:
        update_data["default_environment"] = request.default_environment
    if request.default_plan is not None:
        update_data["default_plan"] = request.default_plan
    if request.use_gravatar is not None:
        update_data["use_gravatar"] = request.use_gravatar
    if request.sidebar_collapsed is not None:
        update_data["sidebar_collapsed"] = request.sidebar_collapsed
    if request.sidebar_pinned is not None:
        update_data["sidebar_pinned"] = request.sidebar_pinned
    if request.density is not None:
        update_data["density"] = request.density
    if request.pinned_workspace_ids is not None:
        update_data["pinned_workspace_ids"] = request.pinned_workspace_ids
    if request.notifications is not None:
        update_data["notifications"] = request.notifications
    if request.dashboard is not None:
        update_data["dashboard"] = request.dashboard
    if request.idle_shutdown_enabled is not None:
        update_data["idle_shutdown_enabled"] = request.idle_shutdown_enabled
    if request.idle_shutdown_timeout is not None:
        # Clamp between 5 and 240 minutes
        update_data["idle_shutdown_timeout"] = max(5, min(request.idle_shutdown_timeout, 240))
    if request.stop_on_logout is not None:
        update_data["stop_on_logout"] = request.stop_on_logout

    # Merge with existing preferences
    new_prefs = {**current_prefs, **update_data}

    # Build user update payload
    user_update: dict = {"preferences": new_prefs}

    # If enabling Gravatar, remove custom avatar file and clear avatar_url
    if request.use_gravatar:
        avatars_dir = os.path.join(settings.upload_dir, "avatars")
        if os.path.isdir(avatars_dir):
            for old_file in os.listdir(avatars_dir):
                if old_file.startswith(str(current_user.id)):
                    os.remove(os.path.join(avatars_dir, old_file))
        user_update["avatar_url"] = ""

    # Update user
    await service.update_user(str(current_user.id), user_update)

    # Return merged preferences with defaults
    defaults = get_default_preferences()
    return {**defaults, **new_prefs}


@router.delete("/")
async def reset_preferences(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Reset preferences to defaults"""
    service = UserService(db)

    await service.update_user(str(current_user.id), {"preferences": get_default_preferences()})

    return get_default_preferences()


@router.get("/defaults")
async def get_default_prefs():
    """Get default preferences"""
    return get_default_preferences()
