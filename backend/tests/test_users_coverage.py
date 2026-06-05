"""Coverage-focused tests for users.py gaps."""

import pytest
import os
import tempfile
from unittest import mock
from io import BytesIO

from app.models.user import User
from app.models.server import Server
from app.models.activity_log import ActivityLog
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember


class TestGetUser:
    """GET /{user_id} coverage."""

    @pytest.mark.asyncio
    async def test_get_own_user(self, client, user_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_get_other_user_as_admin(self, client, admin_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, client, admin_token):
        import uuid
        response = await client.get(
            f"/api/users/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


class TestUpdateUser:
    """PUT /{user_id} coverage."""

    @pytest.mark.asyncio
    async def test_update_self_profile(self, client, user_token, test_user):
        response = await client.put(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"first_name": "SelfUpdated"}
        )
        assert response.status_code == 200
        assert response.json()["first_name"] == "SelfUpdated"

    @pytest.mark.asyncio
    async def test_self_update_role_rejected(self, client, user_token, test_user):
        response = await client.put(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin"}
        )
        assert response.status_code == 403
        assert "role" in response.json()["detail"].lower() or "credit" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_self_update_credits_rejected(self, client, user_token, test_user):
        response = await client.put(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"nuke_balance": 9999}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_update_other_user(self, client, admin_token, test_user):
        response = await client.put(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "moderator", "nuke_balance": 999}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "moderator"
        assert data["nuke_balance"] == 999

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, client, admin_token):
        import uuid
        response = await client.put(
            f"/api/users/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"first_name": "X"}
        )
        assert response.status_code == 404


class TestDeleteUser:
    """DELETE /{user_id} coverage."""

    @pytest.mark.asyncio
    async def test_delete_user(self, client, admin_token, test_user):
        response = await client.delete(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_self_delete_rejected(self, client, admin_token, admin_user):
        response = await client.delete(
            f"/api/users/{admin_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400
        assert "own" in response.json()["detail"].lower()


class TestUserResources:
    """GET /{user_id}/resources coverage."""

    @pytest.mark.asyncio
    async def test_get_user_resources(self, client, user_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}/resources",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        # UserService.get_user_stats returns a dict
        assert isinstance(response.json(), dict)


class TestAvatarUpload:
    """POST /me/avatar coverage."""

    @pytest.mark.asyncio
    async def test_upload_avatar_invalid_type(self, client, user_token):
        response = await client.post(
            "/api/users/me/avatar",
            headers={"Authorization": f"Bearer {user_token}"},
            files={"file": ("test.txt", BytesIO(b"not an image"), "text/plain")}
        )
        assert response.status_code == 400
        assert "invalid file type" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_avatar_too_large(self, client, user_token):
        with mock.patch("app.api.users.settings.max_avatar_size_mb", 0.001):
            response = await client.post(
                "/api/users/me/avatar",
                headers={"Authorization": f"Bearer {user_token}"},
                files={"file": ("test.png", BytesIO(b"x" * 2048), "image/png")}
            )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_avatar_success(self, client, user_token, test_user):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.users.settings.upload_dir", tmpdir):
                response = await client.post(
                    "/api/users/me/avatar",
                    headers={"Authorization": f"Bearer {user_token}"},
                    files={"file": ("test.png", BytesIO(b"fake-png-data"), "image/png")}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["avatar_url"] is not None
        # Gravatar should be disabled
        assert test_user.preferences is None or test_user.preferences.get("use_gravatar") is not True


class TestGetAvatarSuccess:
    """GET /avatar/{filename} success paths."""

    @pytest.mark.asyncio
    async def test_get_avatar_success_png(self, client, test_user):
        with tempfile.TemporaryDirectory() as tmpdir:
            avatars_dir = os.path.join(tmpdir, "avatars")
            os.makedirs(avatars_dir, exist_ok=True)
            filename = f"{test_user.id}.png"
            file_path = os.path.join(avatars_dir, filename)
            with open(file_path, "wb") as f:
                f.write(b"fake-png")

            with mock.patch("app.api.users.settings.upload_dir", tmpdir):
                response = await client.get(f"/api/users/avatar/{filename}")

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"

    @pytest.mark.asyncio
    async def test_get_avatar_success_jpg(self, client, test_user):
        with tempfile.TemporaryDirectory() as tmpdir:
            avatars_dir = os.path.join(tmpdir, "avatars")
            os.makedirs(avatars_dir, exist_ok=True)
            filename = f"{test_user.id}.jpg"
            file_path = os.path.join(avatars_dir, filename)
            with open(file_path, "wb") as f:
                f.write(b"fake-jpg")

            with mock.patch("app.api.users.settings.upload_dir", tmpdir):
                response = await client.get(f"/api/users/avatar/{filename}")

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"


class TestPublicProfile:
    """GET /{user_id}/profile additional coverage."""

    @pytest.mark.asyncio
    async def test_get_public_profile_not_found(self, client, user_token):
        import uuid
        response = await client.get(
            f"/api/users/{uuid.uuid4()}/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_public_profile_self_view(self, client, user_token, test_user):
        test_user.profile_visibility = "private"
        response = await client.get(
            f"/api/users/{test_user.id}/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_get_public_profile_shared_workspace(self, client, user_token, test_user, admin_user, db_session):
        """User can view admin's private profile if they share a workspace."""
        admin_user.profile_visibility = "private"
        ws = SharedWorkspace(name="shared-ws", owner_id=admin_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="member")
        db_session.add(member)
        await db_session.commit()

        response = await client.get(
            f"/api/users/{admin_user.id}/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["username"] == admin_user.username


class TestListUsersFilters:
    """GET / filters coverage."""

    @pytest.mark.asyncio
    async def test_list_users_default(self, client, admin_token):
        response = await client.get(
            "/api/users/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_list_users_role_filter(self, client, admin_token):
        response = await client.get(
            "/api/users/?role=admin",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert all(u["role"] == "admin" for u in data["users"])

    @pytest.mark.asyncio
    async def test_list_users_status_filter(self, client, admin_token, test_user, db_session):
        test_user.is_active = False
        await db_session.commit()

        response = await client.get(
            "/api/users/?status=disabled",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert any(u["id"] == str(test_user.id) for u in data["users"])

    @pytest.mark.asyncio
    async def test_list_users_sort(self, client, admin_token):
        response = await client.get(
            "/api/users/?sort_by=username&sort_order=asc",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_users_pagination(self, client, admin_token):
        response = await client.get(
            "/api/users/?page=1&limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["limit"] == 5

    @pytest.mark.asyncio
    async def test_list_users_unauthorized(self, client, user_token):
        response = await client.get(
            "/api/users/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestCreateUserUnauthorized:
    """POST / RBAC coverage."""

    @pytest.mark.asyncio
    async def test_create_user_unauthorized(self, client, user_token):
        response = await client.post(
            "/api/users/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"username": "x", "email": "x@x.com", "password": "123456"}
        )
        assert response.status_code == 403


class TestMyProfileVisibility:
    """PUT /me/profile visibility coverage."""

    @pytest.mark.asyncio
    async def test_update_profile_visibility(self, client, user_token, test_user):
        response = await client.put(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"profile_visibility": "public"}
        )
        assert response.status_code == 200
        assert response.json()["profile_visibility"] == "public"


class TestMyActivityExtended:
    """GET /me/activity additional coverage."""

    @pytest.mark.asyncio
    async def test_get_my_activity_target_type_filter(self, client, user_token, test_user, db_session):
        log = ActivityLog(actor_id=test_user.id, action="login", target_type="server", target_id=test_user.id)
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?target_type=server",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert len(response.json()["activities"]) == 1

    @pytest.mark.asyncio
    async def test_get_my_activity_date_filter(self, client, user_token, test_user, db_session):
        log = ActivityLog(actor_id=test_user.id, action="login", target_type="user", target_id=test_user.id)
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?from_date=2000-01-01T00:00:00&to_date=2099-12-31T23:59:59",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert len(response.json()["activities"]) == 1

    @pytest.mark.asyncio
    async def test_get_my_activity_invalid_date(self, client, user_token, test_user, db_session):
        log = ActivityLog(actor_id=test_user.id, action="login", target_type="user", target_id=test_user.id)
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?from_date=not-a-date",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_my_activity_pagination(self, client, user_token, test_user, db_session):
        for i in range(3):
            log = ActivityLog(actor_id=test_user.id, action=f"action{i}", target_type="user", target_id=test_user.id)
            db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?page=1&limit=2",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["activities"]) == 2
        assert data["pagination"]["total_pages"] == 2


class TestDisableUserExtended:
    """POST /{user_id}/disable additional coverage."""

    @pytest.mark.asyncio
    async def test_re_enable_user(self, client, admin_token, test_user):
        # First disable
        await client.post(
            f"/api/users/{test_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": True}
        )
        # Then re-enable
        response = await client.post(
            f"/api/users/{test_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": False}
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_disable_user_with_reason(self, client, admin_token, test_user):
        response = await client.post(
            f"/api/users/{test_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": True, "reason": "Violation of terms"}
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestImpersonatePermissions:
    """POST /{user_id}/impersonate RBAC coverage."""

    @pytest.mark.asyncio
    async def test_impersonate_forbidden_for_user(self, client, user_token, test_user):
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestUserServersAdmin:
    """GET /{user_id}/servers admin coverage."""

    @pytest.mark.asyncio
    async def test_get_other_user_servers_as_admin(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-admin", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/users/{test_user.id}/servers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "srv-admin"


class TestSerializeUserEdgeCases:
    """serialize_user with None fields."""

    @pytest.mark.asyncio
    async def test_serialize_user_none_dates(self, test_user):
        from app.api.users import serialize_user
        test_user.last_login = None
        test_user.created_at = None
        test_user.updated_at = None
        test_user.profile = None
        test_user.preferences = None
        result = serialize_user(test_user)
        assert result["last_login"] is None
        assert result["created_at"] is None
        assert result["updated_at"] is None
        assert result["profile"] == {}
        assert result["preferences"] == {}
