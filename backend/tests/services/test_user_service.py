"""Tests for UserService business logic."""

import pytest
import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import select, and_, func

from app.services.user_service import UserService
from app.models.user import User
from app.models.server import Server


class TestUserServiceGetBy:
    """Tests for get_by_id, get_by_username, get_by_email."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, db_session, test_user):
        """get_by_id should return user when found."""
        service = UserService(db_session)
        result = await service.get_by_id(str(test_user.id))
        assert result is not None
        assert result.username == test_user.username

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session):
        """get_by_id should return None when not found."""
        service = UserService(db_session)
        result = await service.get_by_id(str(uuid_mod.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_username_found(self, db_session, test_user):
        """get_by_username should return user when found."""
        service = UserService(db_session)
        result = await service.get_by_username(test_user.username)
        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_get_by_username_not_found(self, db_session):
        """get_by_username should return None when not found."""
        service = UserService(db_session)
        result = await service.get_by_username("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_email_found(self, db_session, test_user):
        """get_by_email should return user when found."""
        service = UserService(db_session)
        result = await service.get_by_email(test_user.email)
        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_get_by_email_not_found(self, db_session):
        """get_by_email should return None when not found."""
        service = UserService(db_session)
        result = await service.get_by_email("nobody@example.com")
        assert result is None


class TestUserServiceList:
    """Tests for list_users."""

    @pytest.mark.asyncio
    async def test_list_users_no_filters(self, db_session, test_user, admin_user):
        """list_users should return all users."""
        service = UserService(db_session)
        result = await service.list_users()
        assert result["pagination"]["total"] >= 2
        usernames = [u.username for u in result["users"]]
        assert test_user.username in usernames
        assert admin_user.username in usernames

    @pytest.mark.asyncio
    async def test_list_users_filter_by_role(self, db_session, test_user, admin_user):
        """list_users should filter by role."""
        service = UserService(db_session)
        result = await service.list_users(role="admin")
        usernames = [u.username for u in result["users"]]
        assert admin_user.username in usernames
        assert test_user.username not in usernames

    @pytest.mark.asyncio
    async def test_list_users_filter_by_status_active(self, db_session, test_user):
        """list_users should filter by active status."""
        service = UserService(db_session)
        result = await service.list_users(status="active")
        usernames = [u.username for u in result["users"]]
        assert test_user.username in usernames

    @pytest.mark.asyncio
    async def test_list_users_filter_by_status_disabled(self, db_session):
        """list_users should filter by disabled status."""
        user = User(
            username="disableduser",
            email="disabled@test.com",
            password_hash="hash",
            role="user",
            is_active=False,
        )
        db_session.add(user)
        await db_session.commit()

        service = UserService(db_session)
        result = await service.list_users(status="disabled")
        usernames = [u.username for u in result["users"]]
        assert "disableduser" in usernames

    @pytest.mark.asyncio
    async def test_list_users_search(self, db_session, test_user):
        """list_users should search across fields."""
        service = UserService(db_session)
        result = await service.list_users(search=test_user.username)
        usernames = [u.username for u in result["users"]]
        assert test_user.username in usernames

    @pytest.mark.asyncio
    async def test_list_users_pagination(self, db_session, test_user, admin_user):
        """list_users should respect pagination."""
        service = UserService(db_session)
        result = await service.list_users(page=1, limit=1)
        assert len(result["users"]) == 1
        assert result["pagination"]["total_pages"] >= 2

    @pytest.mark.asyncio
    async def test_list_users_sort_asc(self, db_session, test_user, admin_user):
        """list_users should support ascending sort."""
        service = UserService(db_session)
        result = await service.list_users(sort_by="username", sort_order="asc")
        usernames = [u.username for u in result["users"]]
        assert usernames == sorted(usernames)


class TestUserServiceCreate:
    """Tests for create_user."""

    @pytest.mark.asyncio
    async def test_create_user_success(self, db_session):
        """create_user should create a new user."""
        service = UserService(db_session)
        user = await service.create_user(
            username="newuser",
            email="new@example.com",
            password="password123",
            role="user",
            first_name="New",
            last_name="User",
            credits=1000,
        )
        assert user.username == "newuser"
        assert user.nuke_balance == 1000
        assert user.daily_allowance == 1000

    @pytest.mark.asyncio
    async def test_create_user_invalid_role(self, db_session):
        """create_user should reject invalid role."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_user(
                username="badrole", email="bad@example.com", password="password123", role="hacker"
            )
        assert "Invalid role" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_user_duplicate_username(self, db_session, test_user):
        """create_user should reject duplicate username."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_user(
                username=test_user.username, email="unique@example.com", password="password123"
            )
        assert "Username already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_user_duplicate_email(self, db_session, test_user):
        """create_user should reject duplicate email."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_user(
                username="uniqueuser", email=test_user.email, password="password123"
            )
        assert "Email already exists" in str(exc_info.value)


class TestUserServiceUpdate:
    """Tests for update_user."""

    @pytest.mark.asyncio
    async def test_update_user_basic_fields(self, db_session, test_user):
        """update_user should update allowed fields."""
        service = UserService(db_session)
        updated = await service.update_user(
            str(test_user.id),
            {"first_name": "Updated", "last_name": "Name", "email": "updated@example.com"},
        )
        assert updated.first_name == "Updated"
        assert updated.last_name == "Name"
        assert updated.email == "updated@example.com"

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, db_session):
        """update_user should raise when user not found."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.update_user(str(uuid_mod.uuid4()), {"first_name": "X"})
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_user_role_by_admin(self, db_session, test_user, admin_user):
        """Admin should be able to update role."""
        service = UserService(db_session)
        updated = await service.update_user(
            str(test_user.id), {"role": "moderator"}, updated_by=admin_user
        )
        assert updated.role == "moderator"

    @pytest.mark.asyncio
    async def test_update_user_role_forbidden_for_user(self, db_session, test_user):
        """Regular user should not update role."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.update_user(str(test_user.id), {"role": "admin"}, updated_by=test_user)
        assert "Insufficient permissions" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_user_credits_by_admin(self, db_session, test_user, admin_user):
        """Admin should be able to update credits."""
        service = UserService(db_session)
        updated = await service.update_user(
            str(test_user.id), {"nuke_balance": 9999}, updated_by=admin_user
        )
        assert updated.nuke_balance == 9999


class TestUserServiceDelete:
    """Tests for delete_user."""

    @pytest.mark.asyncio
    async def test_delete_user_success(self, db_session):
        """delete_user should remove user."""
        user = User(
            username="todelete",
            email="delete@example.com",
            password_hash="hash",
            role="user",
        )
        db_session.add(user)
        await db_session.commit()

        service = UserService(db_session)
        await service.delete_user(str(user.id))

        result = await db_session.execute(select(User).where(User.id == user.id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_user_not_found(self, db_session):
        """delete_user should raise when user not found."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.delete_user(str(uuid_mod.uuid4()))
        assert "not found" in str(exc_info.value)


class TestUserServiceDisable:
    """Tests for disable_user."""

    @pytest.mark.asyncio
    async def test_disable_user(self, db_session, test_user):
        """disable_user should deactivate user."""
        service = UserService(db_session)
        updated = await service.disable_user(str(test_user.id), disabled=True, reason="Test")
        assert updated.is_active is False
        assert updated.security.get("disabled_reason") == "Test"

    @pytest.mark.asyncio
    async def test_enable_user(self, db_session, test_user):
        """disable_user with disabled=False should activate user."""
        service = UserService(db_session)
        await service.disable_user(str(test_user.id), disabled=True, reason="Test")
        updated = await service.disable_user(str(test_user.id), disabled=False)
        assert updated.is_active is True
        assert "disabled_reason" not in updated.security

    @pytest.mark.asyncio
    async def test_disable_user_not_found(self, db_session):
        """disable_user should raise when user not found."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.disable_user(str(uuid_mod.uuid4()))
        assert "not found" in str(exc_info.value)


class TestUserServiceChangePassword:
    """Tests for change_password."""

    @pytest.mark.asyncio
    async def test_change_password_success(self, db_session, test_user):
        """change_password should update password."""
        service = UserService(db_session)
        result = await service.change_password(
            str(test_user.id), current_password="testpass123", new_password="newpassword456"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, db_session, test_user):
        """change_password should fail with wrong current password."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.change_password(
                str(test_user.id), current_password="wrongpassword", new_password="newpassword456"
            )
        assert "incorrect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_change_password_user_not_found(self, db_session):
        """change_password should raise when user not found."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.change_password(
                str(uuid_mod.uuid4()), current_password="old", new_password="new"
            )
        assert "not found" in str(exc_info.value)


class TestUserServiceDiscover:
    """Tests for discover_users."""

    @pytest.mark.asyncio
    async def test_discover_public_users(self, db_session):
        """discover_users should return public users."""
        user = User(
            username="publicuser",
            email="public@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
            profile_visibility="public",
        )
        db_session.add(user)
        await db_session.commit()

        service = UserService(db_session)
        result = await service.discover_users()
        usernames = [u.username for u in result]
        assert "publicuser" in usernames

    @pytest.mark.asyncio
    async def test_discover_search(self, db_session):
        """discover_users should filter by search."""
        user = User(
            username="searchme",
            email="search@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
            profile_visibility="public",
            first_name="Searchable",
        )
        db_session.add(user)
        await db_session.commit()

        service = UserService(db_session)
        result = await service.discover_users(search="search")
        usernames = [u.username for u in result]
        assert "searchme" in usernames

    @pytest.mark.asyncio
    async def test_discover_private_users_hidden(self, db_session):
        """discover_users should not return private users."""
        user = User(
            username="privateuser",
            email="private@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
            profile_visibility="private",
        )
        db_session.add(user)
        await db_session.commit()

        service = UserService(db_session)
        result = await service.discover_users()
        usernames = [u.username for u in result]
        assert "privateuser" not in usernames


class TestUserServiceStats:
    """Tests for get_user_stats."""

    @pytest.mark.asyncio
    async def test_get_user_stats(self, db_session, test_user):
        """get_user_stats should return aggregated stats."""
        server = Server(
            name="test-server",
            user_id=test_user.id,
            status="running",
            plan_id=uuid_mod.uuid4(),
        )
        db_session.add(server)
        await db_session.commit()

        service = UserService(db_session)
        stats = await service.get_user_stats(str(test_user.id))
        assert stats["user_id"] == str(test_user.id)
        assert stats["server_count"] == 1
        assert stats["running_servers"] == 1
        assert stats["nuke_balance"] == test_user.nuke_balance

    @pytest.mark.asyncio
    async def test_get_user_stats_not_found(self, db_session):
        """get_user_stats should raise when user not found."""
        service = UserService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.get_user_stats(str(uuid_mod.uuid4()))
        assert "not found" in str(exc_info.value)
