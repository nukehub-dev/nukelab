"""Tests for User Preferences API endpoints."""

import pytest


class TestPreferencesDefaults:
    """Default preferences retrieval tests."""

    @pytest.mark.asyncio
    async def test_get_default_preferences(self, client, test_user, user_token):
        """Fresh user should have sensible default preferences."""
        response = await client.get(
            "/api/preferences/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["theme"] == "default"
        assert data["accent_color"] is None
        assert data["oled_mode"] is False
        assert data["sidebar_collapsed"] is False
        assert data["sidebar_pinned"] is True


class TestPreferencesUpdate:
    """Preferences modification tests."""

    @pytest.mark.asyncio
    async def test_update_theme_and_accent(self, client, user_token):
        """User should be able to change theme and accent color."""
        response = await client.put(
            "/api/preferences/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "theme": "ocean",
                "accent_color": "oklch(0.6 0.15 233.7)",
                "oled_mode": True,
                "sidebar_collapsed": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["theme"] == "ocean"
        assert data["accent_color"] == "oklch(0.6 0.15 233.7)"
        assert data["oled_mode"] is True
        assert data["sidebar_collapsed"] is True

    @pytest.mark.asyncio
    async def test_all_valid_themes_accepted(self, client, user_token):
        """All 8 curated themes should be valid."""
        valid_themes = [
            "default", "graphite", "ocean", "amber",
            "github", "nord", "everforest", "rosepine"
        ]
        
        for theme in valid_themes:
            response = await client.put(
                "/api/preferences/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"theme": theme}
            )
            assert response.status_code == 200, f"Theme '{theme}' should be valid"
