"""Extended tests for Users API endpoints."""

import pytest
from unittest import mock

from app.models.user import User
from app.models.activity_log import ActivityLog
from app.models.server import Server


class TestDiscoverUsers:
    @pytest.mark.asyncio
    async def test_discover_public_users(self, client, user_token, admin_user, db_session):
        admin_user.profile_visibility = "public"
        await db_session.commit()

        response = await client.get(
            "/api/users/discover",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert any(u["username"] == "adminuser" for u in data["users"])

    @pytest.mark.asyncio
    async def test_discover_search(self, client, user_token, admin_user, db_session):
        admin_user.profile_visibility = "public"
        await db_session.commit()

        response = await client.get(
            "/api/users/discover?search=admin",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert any(u["username"] == "adminuser" for u in data["users"])


class TestMyActivity:
    @pytest.mark.asyncio
    async def test_get_my_activity(self, client, user_token, test_user, db_session):
        log = ActivityLog(
            actor_id=test_user.id,
            action="login",
            target_type="user",
            target_id=test_user.id,
            details={"ip": "127.0.0.1"}
        )
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "activities" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_get_my_activity_filter_action(self, client, user_token, test_user, db_session):
        log = ActivityLog(
            actor_id=test_user.id,
            action="logout",
            target_type="user",
            target_id=test_user.id,
        )
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?action=logout",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["activities"]) == 1
        assert data["activities"][0]["action"] == "logout"


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password_success(self, client, user_token, test_user, db_session):
        from app.api.auth import get_password_hash
        test_user.password_hash = get_password_hash("oldpassword")
        await db_session.commit()

        response = await client.post(
            "/api/users/me/change-password",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"current_password": "oldpassword", "new_password": "newpassword123"}
        )
        assert response.status_code == 200
        assert "changed" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, client, user_token, test_user, db_session):
        from app.api.auth import get_password_hash
        test_user.password_hash = get_password_hash("oldpassword")
        await db_session.commit()

        response = await client.post(
            "/api/users/me/change-password",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"current_password": "wrong", "new_password": "newpassword123"}
        )
        assert response.status_code == 400


class TestDisableUser:
    @pytest.mark.asyncio
    async def test_disable_user(self, client, admin_token, test_user):
        response = await client.post(
            f"/api/users/{test_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": True, "reason": "Test disable"}
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_self_disable_rejected(self, client, admin_token, admin_user):
        response = await client.post(
            f"/api/users/{admin_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": True}
        )
        assert response.status_code == 400
        assert "own" in response.json()["detail"].lower()


class TestImpersonateUser:
    @pytest.mark.asyncio
    async def test_impersonate_user(self, client, superadmin_token, test_user):
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {superadmin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["impersonated_user"]["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_impersonate_not_found(self, client, admin_token):
        import uuid
        response = await client.post(
            f"/api/users/{uuid.uuid4()}/impersonate",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_impersonate_not_found(self, client, superadmin_token):
        import uuid
        response = await client.post(
            f"/api/users/{uuid.uuid4()}/impersonate",
            headers={"Authorization": f"Bearer {superadmin_token}"}
        )
        assert response.status_code == 404


class TestUserServers:
    @pytest.mark.asyncio
    async def test_get_user_servers(self, client, user_token, test_user, db_session):
        server = Server(name="srv1", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/users/{test_user.id}/servers",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "srv1"

    @pytest.mark.asyncio
    async def test_get_other_user_servers_forbidden(self, client, user_token, admin_user, db_session):
        server = Server(name="srv2", user_id=admin_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/users/{admin_user.id}/servers",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403
