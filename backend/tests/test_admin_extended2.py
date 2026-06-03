"""Extended tests for admin.py — error branches and filter coverage."""

import pytest
import pytest_asyncio
import uuid as uuid_mod
from unittest import mock
from datetime import datetime, timedelta

from app.models.user import User
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.shared_workspace import SharedWorkspace
from app.models.volume import Volume
from app.models.activity_log import ActivityLog


# ─────────────────────────────────────────────────────────────
# POST /users/bulk-action — exception catch path
# ─────────────────────────────────────────────────────────────

class TestUsersBulkAction:
    """Tests for users bulk-action error branches."""

    @pytest.mark.asyncio
    async def test_users_bulk_action_enable(self, client, admin_token, test_user, db_session):
        """Enable action should work."""
        test_user.is_active = False
        await db_session.commit()

        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "enable", "user_ids": [str(test_user.id)]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["success"]) == 1

    @pytest.mark.asyncio
    async def test_users_bulk_action_exception(self, client, admin_token):
        """Exception on one user should be caught and reported."""
        with mock.patch("app.api.admin.UserService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.disable_user = mock.AsyncMock(side_effect=Exception("user locked"))

            response = await client.post(
                "/api/admin/users/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "disable", "user_ids": [str(uuid_mod.uuid4())]},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "user locked" in data["results"]["failed"][0]["error"].lower()


# ─────────────────────────────────────────────────────────────
# POST /servers/bulk-action — stop/delete + exception
# ─────────────────────────────────────────────────────────────

class TestServersBulkAction:
    """Tests for servers bulk-action error branches."""

    @pytest.mark.asyncio
    async def test_servers_bulk_action_delete(self, client, admin_token, test_user, db_session):
        """Delete action should call delete_container and not broadcast."""
        plan = ServerPlan(
            name="bulk-plan", slug="bulk-plan",
            cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0,
            visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="bulk-env", slug="bulk-env", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(
            name="bulk-srv", user_id=test_user.id, status="stopped",
            container_id="bulk-cid", plan_id=plan.id, environment_id=env.id,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.container.spawner.spawner") as mock_spawner:
            mock_spawner.delete = mock.AsyncMock(return_value=True)
            with mock.patch("app.api.admin.broadcast_server_status_change") as mock_bc:
                response = await client.post(
                    "/api/admin/servers/bulk-action",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"action": "delete", "server_ids": [str(server.id)]},
                )

        assert response.status_code == 200
        mock_spawner.delete.assert_awaited_once_with("bulk-cid")
        mock_bc.assert_not_called()

    @pytest.mark.asyncio
    async def test_servers_bulk_action_spawner_exception(self, client, admin_token, test_user, db_session):
        """Spawner exception should be caught per server."""
        plan = ServerPlan(
            name="bulk-plan2", slug="bulk-plan2",
            cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0,
            visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="bulk-env2", slug="bulk-env2", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(
            name="bulk-srv2", user_id=test_user.id, status="running",
            container_id="bulk-cid2", plan_id=plan.id, environment_id=env.id,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.container.spawner.spawner") as mock_spawner:
            mock_spawner.stop = mock.AsyncMock(side_effect=Exception("docker down"))
            response = await client.post(
                "/api/admin/servers/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "stop", "server_ids": [str(server.id)]},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "docker down" in data["results"]["failed"][0]["error"].lower()


# ─────────────────────────────────────────────────────────────
# PUT /permissions/{role} — invalid permissions + save failure
# ─────────────────────────────────────────────────────────────

class TestPermissions:
    """Tests for permissions endpoint error branches."""

    @pytest.mark.asyncio
    async def test_permissions_invalid_permission(self, client, admin_token):
        """Invalid permission should return 400."""
        response = await client.put(
            "/api/admin/permissions/admin",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": ["servers:read_own", "invalid_permission"]},
        )

        assert response.status_code == 400
        assert "invalid permission" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_permissions_save_failure_silent(self, client, admin_token):
        """save_role_permissions_to_db exception should be silently ignored."""
        with mock.patch("app.core.roles.save_role_permissions_to_db") as mock_save:
            mock_save.side_effect = Exception("db locked")
            response = await client.put(
                "/api/admin/permissions/admin",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"permissions": ["servers:read_own"]},
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_permissions_super_admin_blocked(self, client, admin_token):
        """Cannot modify super_admin permissions."""
        response = await client.put(
            "/api/admin/permissions/super_admin",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": ["servers:read_own"]},
        )

        assert response.status_code == 403
        assert "cannot modify" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# POST /email-test — SMTP failure
# ─────────────────────────────────────────────────────────────

class TestEmailTest:
    """Tests for email-test endpoint error branches."""

    @pytest.mark.asyncio
    async def test_email_test_send_failure(self, client, admin_token):
        """SMTP send failure should return 500."""
        with mock.patch("app.services.email_service.EmailService") as mock_email_cls:
            mock_email = mock_email_cls.return_value
            mock_email.enabled = True
            mock_email.send_email = mock.AsyncMock(return_value={"success": False, "error": "SMTP rejected"})
            mock_email.smtp_host = "smtp.test"
            mock_email.smtp_port = 587

            response = await client.post(
                "/api/admin/email-test",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={},
            )

        assert response.status_code == 500
        assert "failed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_email_test_disabled(self, client, admin_token):
        """SMTP disabled should return 400."""
        with mock.patch("app.services.email_service.EmailService") as mock_email_cls:
            mock_email = mock_email_cls.return_value
            mock_email.enabled = False

            response = await client.post(
                "/api/admin/email-test",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={},
            )

        assert response.status_code == 400
        assert "not configured" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# GET /email-status — SMTP connection error
# ─────────────────────────────────────────────────────────────

class TestEmailStatus:
    """Tests for email-status endpoint error branches."""

    @pytest.mark.asyncio
    async def test_email_status_connection_error(self, client, admin_token):
        """SMTP connection error should return 200 with error status."""
        with mock.patch("app.services.email_service.EmailService") as mock_email_cls:
            mock_email = mock_email_cls.return_value
            mock_email.enabled = True
            mock_email.smtp_host = "smtp.test"
            mock_email.smtp_port = 587
            mock_email.smtp_user = None
            mock_email.smtp_password = None
            mock_email.use_tls = False
            mock_email.verify_certs = False

            with mock.patch("aiosmtplib.SMTP") as mock_smtp_cls:
                mock_smtp = mock_smtp_cls.return_value
                mock_smtp.connect = mock.AsyncMock(side_effect=Exception("connection refused"))

                response = await client.get(
                    "/api/admin/email-status",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_email_status_disabled(self, client, admin_token):
        """SMTP disabled should return 200 with disabled status."""
        with mock.patch("app.services.email_service.EmailService") as mock_email_cls:
            mock_email = mock_email_cls.return_value
            mock_email.enabled = False

            response = await client.get(
                "/api/admin/email-status",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"


# ─────────────────────────────────────────────────────────────
# GET /activity — date filters
# ─────────────────────────────────────────────────────────────

class TestActivityFilters:
    """Tests for activity endpoint filter coverage."""

    @pytest.mark.asyncio
    async def test_activity_with_date_filters(self, client, admin_token, test_user, db_session):
        """Should filter by from_date and to_date."""
        log = ActivityLog(
            action="test_action",
            target_type="server",
            target_id=uuid_mod.uuid4(),
            actor_id=test_user.id,
            created_at=datetime.utcnow(),
        )
        db_session.add(log)
        await db_session.commit()

        from_date = (datetime.utcnow() - timedelta(days=1)).isoformat()
        to_date = (datetime.utcnow() + timedelta(days=1)).isoformat()

        response = await client.get(
            f"/api/admin/activity?from_date={from_date}&to_date={to_date}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) >= 1


# ─────────────────────────────────────────────────────────────
# GET /servers — status + user_id filters
# ─────────────────────────────────────────────────────────────

class TestServersFilter:
    """Tests for servers list filter coverage."""

    @pytest.mark.asyncio
    async def test_servers_status_filter(self, client, admin_token, test_user, db_session):
        """Should filter by status."""
        plan = ServerPlan(
            name="filter-plan", slug="filter-plan",
            cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0,
            visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="filter-env", slug="filter-env", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        srv = Server(
            name="filter-srv", user_id=test_user.id, status="running",
            container_id="fcid", plan_id=plan.id, environment_id=env.id,
        )
        db_session.add(srv)
        await db_session.commit()

        response = await client.get(
            "/api/admin/servers?status=running",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert any(s["name"] == "filter-srv" for s in data["servers"])

    @pytest.mark.asyncio
    async def test_servers_user_id_filter(self, client, admin_token, test_user, db_session):
        """Should filter by user_id."""
        plan = ServerPlan(
            name="filter-plan2", slug="filter-plan2",
            cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0,
            visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="filter-env2", slug="filter-env2", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        srv = Server(
            name="filter-srv2", user_id=test_user.id, status="stopped",
            plan_id=plan.id, environment_id=env.id,
        )
        db_session.add(srv)
        await db_session.commit()

        response = await client.get(
            f"/api/admin/servers?user_id={test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert any(s["name"] == "filter-srv2" for s in data["servers"])


# ─────────────────────────────────────────────────────────────
# DELETE /volumes/{id} — ValueError catch
# ─────────────────────────────────────────────────────────────

class TestAdminVolumeDelete:
    """Tests for admin volume delete error branches."""

    @pytest.mark.asyncio
    async def test_admin_delete_volume_value_error(self, client, admin_token, test_user, db_session):
        """ValueError from delete_volume should return 400."""
        volume = Volume(
            name="admin-del-vol",
            display_name="Admin Delete Volume",
            owner_id=test_user.id,
            size_bytes=1073741824,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with mock.patch("app.api.admin.VolumeService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_volume = mock.AsyncMock(return_value=volume)
            mock_svc.delete_volume = mock.AsyncMock(side_effect=ValueError("volume in use"))

            response = await client.delete(
                f"/api/admin/volumes/{volume.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 400
        assert "volume in use" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# POST /credits/grant-bulk — exception catch
# ─────────────────────────────────────────────────────────────

class TestCreditsGrantBulk:
    """Tests for credits grant-bulk error branches."""

    @pytest.mark.asyncio
    async def test_grant_bulk_exception(self, client, admin_token, test_user):
        """Exception during grant should be caught."""
        with mock.patch("app.api.admin.CreditService") as mock_credit_cls:
            mock_credit = mock_credit_cls.return_value
            mock_credit.grant_credits = mock.AsyncMock(side_effect=Exception("payment gateway down"))

            response = await client.post(
                "/api/admin/credits/grant-bulk",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"user_ids": [str(test_user.id)], "amount": 100, "reason": "test"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "payment gateway down" in data["results"]["failed"][0]["error"].lower()
