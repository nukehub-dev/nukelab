"""
Preferences API endpoints.
"""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import UserService

router = APIRouter()


class PreferencesUpdateRequest(BaseModel):
    theme: Optional[str] = Field(None, description="Theme: default, graphite, ocean, amber, github, nord, everforest, rosepine")
    accent_color: Optional[str] = Field(None, description="Custom accent color (OKLCH value)")
    oled_mode: Optional[bool] = Field(None, description="OLED dark mode")
    use_gravatar: Optional[bool] = Field(None, description="Use Gravatar for profile image")
    language: Optional[str] = Field(None, description="Language code")
    timezone: Optional[str] = Field(None, description="Timezone")
    default_environment: Optional[str] = Field(None, description="Default environment")
    default_plan: Optional[str] = Field(None, description="Default plan")
    notifications: Optional[dict] = Field(None, description="Notification preferences")
    dashboard: Optional[dict] = Field(None, description="Dashboard preferences")
    sidebar_collapsed: Optional[bool] = Field(None, description="Sidebar collapsed state")
    sidebar_pinned: Optional[bool] = Field(None, description="Sidebar pinned state")


class PreferencesResponse(BaseModel):
    theme: str
    accent_color: Optional[str]
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
                "system_updates": True
            }
        },
        "dashboard": {
            "default_view": "grid",
            "show_inactive_servers": False,
            "auto_refresh_interval": 30,
            "metrics_time_range": "1h"
        }
    }


@router.get("/")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
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
    db: AsyncSession = Depends(get_db)
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
    if request.notifications is not None:
        update_data["notifications"] = request.notifications
    if request.dashboard is not None:
        update_data["dashboard"] = request.dashboard
    
    # Merge with existing preferences
    new_prefs = {**current_prefs, **update_data}
    
    # Update user
    await service.update_user(
        str(current_user.id),
        {"preferences": new_prefs}
    )
    
    # Return merged preferences with defaults
    defaults = get_default_preferences()
    return {**defaults, **new_prefs}


@router.delete("/")
async def reset_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reset preferences to defaults"""
    service = UserService(db)
    
    await service.update_user(
        str(current_user.id),
        {"preferences": get_default_preferences()}
    )
    
    return get_default_preferences()


@router.get("/defaults")
async def get_default_prefs():
    """Get default preferences"""
    return get_default_preferences()
