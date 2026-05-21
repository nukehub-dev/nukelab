"""Tests for User model and User API endpoints."""

import pytest
import hashlib

from app.models.user import User


class TestUserModel:
    """User model property and method tests."""

    @pytest.mark.asyncio
    async def test_display_name_combines_first_and_last(self, test_user):
        """display_name should combine first_name and last_name."""
        assert test_user.display_name == "Test User"

    @pytest.mark.asyncio
    async def test_display_name_fallback_to_username(self, test_user):
        """display_name should fall back to username when names are empty."""
        test_user.first_name = None
        test_user.last_name = None
        assert test_user.display_name == "testuser"

    @pytest.mark.asyncio
    async def test_gravatar_url_generation(self, test_user):
        """Gravatar URL should be generated from email hash."""
        expected_hash = hashlib.md5("test@example.com".lower().strip().encode()).hexdigest()
        expected_url = f"https://www.gravatar.com/avatar/{expected_hash}?s=200&d=identicon&r=pg"
        
        # Direct gravatar generation always works
        assert test_user.get_gravatar_url() == expected_url
        
        # Gravatar is disabled by default for privacy
        assert test_user.get_avatar_url() == ""
        
        # When explicitly enabled, should return Gravatar URL
        test_user.preferences = {"use_gravatar": True}
        assert test_user.get_avatar_url() == expected_url

    @pytest.mark.asyncio
    async def test_custom_avatar_when_gravatar_disabled(self, test_user):
        """get_avatar_url should return custom URL when use_gravatar is false."""
        test_user.avatar_url = "https://example.com/avatar.png"
        test_user.preferences = {"use_gravatar": False}
        
        assert test_user.get_avatar_url() == "https://example.com/avatar.png"

    @pytest.mark.asyncio
    async def test_to_dict_includes_new_fields(self, test_user):
        """User serialization should include first_name, last_name, display_name, avatar_url."""
        user_dict = test_user.to_dict()
        
        assert "first_name" in user_dict
        assert "last_name" in user_dict
        assert "display_name" in user_dict
        assert "avatar_url" in user_dict
        assert "full_name" not in user_dict


class TestUserCreateAPI:
    """User creation endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_user_with_names(self, client, admin_token):
        """Admin should be able to create user with first_name and last_name."""
        response = await client.post(
            "/api/users/",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "newpass123",
                "first_name": "New",
                "last_name": "Person",
                "role": "user"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["first_name"] == "New"
        assert data["last_name"] == "Person"
        assert data["display_name"] == "New Person"
        assert "avatar_url" in data


class TestUserProfileAPI:
    """Current user profile endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_my_profile(self, client, user_token, test_user):
        """User should be able to fetch their own profile."""
        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username
        assert data["display_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_update_my_profile(self, client, user_token):
        """User should be able to update first_name, last_name, avatar_url, preferences."""
        response = await client.put(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "first_name": "Updated",
                "last_name": "Name",
                "avatar_url": "https://example.com/new-avatar.png",
                "preferences": {"use_gravatar": False}
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "Name"
        assert data["display_name"] == "Updated Name"
        assert data["avatar_url"] == "https://example.com/new-avatar.png"


class TestUserSearchAPI:
    """User search and listing endpoint tests."""

    @pytest.mark.asyncio
    async def test_search_users_by_name(self, client, admin_user, admin_token):
        """Admin should be able to search users by first_name."""
        response = await client.get(
            "/api/users/?search=Admin",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["users"]) > 0


class TestPublicProfileAPI:
    """Public profile endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_public_profile_of_public_user(self, client, user_token, admin_user):
        """Should return public profile for a user with public visibility."""
        from app.db.session import get_db
        async for db in get_db():
            admin_user.profile_visibility = "public"
            await db.commit()
            break

        response = await client.get(
            f"/api/users/{admin_user.id}/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == admin_user.username
        assert "display_name" in data
        assert "avatar_url" in data

    @pytest.mark.asyncio
    async def test_get_private_profile_returns_404(self, client, user_token, admin_user):
        """Should return 404 for private user with no shared workspace."""
        from app.db.session import get_db
        async for db in get_db():
            admin_user.profile_visibility = "private"
            await db.commit()
            break

        response = await client.get(
            f"/api/users/{admin_user.id}/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404
