"""Coverage-focused tests for admin.py gaps."""

import pytest
from unittest import mock
from datetime import datetime, UTC

from app.models.user import User
from app.models.server import Server
from app.models.activity_log import ActivityLog
from app.models.health_check import HealthCheck


class TestBulkUserActionUnknown:
    """POST /users/bulk-action unknown action branch."""

    @pytest.mark.asyncio
    async def test_bulk_user_unknown_action(self, client, admin_token, test_user):
        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "unknown", "user_ids": [str(test_user.id)]}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "unknown action" in data["results"]["failed"][0]["error"].lower()


class TestBulkServerActionBranches:
    """POST /servers/bulk-action not-found + missing container_id + unknown action."""

    @pytest.mark.asyncio
    async def test_bulk_server_not_found(self, client, admin_token):
        import uuid
        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "start", "server_ids": [str(uuid.uuid4())]}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "not found" in data["results"]["failed"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_bulk_server_missing_container_id(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-no-container", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "start", "server_ids": [str(server.id)]}
        )
        assert response.status_code == 200
        assert str(server.id) in response.json()["results"]["success"]

    @pytest.mark.asyncio
    async def test_bulk_server_unknown_action(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-unknown", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "unknown", "server_ids": [str(server.id)]}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "unknown action" in data["results"]["failed"][0]["error"].lower()


class TestSystemHealthDbError:
    """GET /system/health DB exception catch."""

    @pytest.mark.asyncio
    async def test_system_health_db_error(self, client, admin_token):
        with mock.patch("app.api.admin.select") as mock_select:
            mock_select.return_value.select_from.side_effect = RuntimeError("DB down")
            response = await client.get(
                "/api/admin/system/health",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "error" in data["database"].lower()


class TestEmailTestSuccess:
    """POST /email-test success + no-recipient edge case."""

    @pytest.mark.asyncio
    async def test_email_test_success(self, client, admin_token, admin_user):
        with mock.patch("app.services.email_service.EmailService") as mock_service:
            instance = mock_service.return_value
            instance.enabled = True
            instance.smtp_host = "localhost"
            instance.smtp_port = 25
            instance.send_email = mock.AsyncMock(return_value={"success": True})
            response = await client.post(
                "/api/admin/email-test",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"to_email": "test@example.com"}
            )
            assert response.status_code == 200
            assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_email_test_no_recipient(self, client, admin_token, admin_user, db_session):
        admin_user.email = ""
        await db_session.commit()
        with mock.patch("app.services.email_service.EmailService") as mock_service:
            instance = mock_service.return_value
            instance.enabled = True
            response = await client.post(
                "/api/admin/email-test",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={}
            )
            assert response.status_code == 400
            assert "no recipient" in response.json()["detail"].lower()


class TestEmailStatusConnected:
    """GET /email-status connected path."""

    @pytest.mark.asyncio
    async def test_email_status_connected(self, client, admin_token):
        with mock.patch("app.services.email_service.EmailService") as mock_service:
            instance = mock_service.return_value
            instance.enabled = True
            instance.smtp_host = "localhost"
            instance.smtp_port = 25
            instance.use_tls = False
            instance.verify_certs = False
            instance.smtp_user = None
            instance.smtp_password = None
            with mock.patch("aiosmtplib.SMTP") as mock_smtp:
                mock_instance = mock_smtp.return_value
                mock_instance.connect = mock.AsyncMock()
                mock_instance.quit = mock.AsyncMock()
                response = await client.get(
                    "/api/admin/email-status",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "connected"


class TestActivityExportFilters:
    """GET /activity/export with query filters."""

    @pytest.mark.asyncio
    async def test_export_activity_with_filters(self, client, admin_token, test_user, db_session):
        log = ActivityLog(
            actor_id=test_user.id,
            action="login",
            target_type="user",
            target_id=test_user.id,
            ip_address="127.0.0.1"
        )
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            f"/api/admin/activity/export?user_id={test_user.id}&action=login&target_type=user&format=json",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["action"] == "login"

    @pytest.mark.asyncio
    async def test_export_activity_csv(self, client, admin_token, test_user, db_session):
        log = ActivityLog(
            actor_id=test_user.id,
            action="logout",
            target_type="user",
            target_id=test_user.id,
        )
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/admin/activity/export?format=csv",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")


class TestRetentionUpdateValidation:
    """PUT /retention ValueError catch."""

    @pytest.mark.asyncio
    async def test_retention_update_validation_error(self, client, admin_token):
        with mock.patch("app.api.admin.RetentionService") as mock_service:
            instance = mock_service.return_value
            instance.set_policy = mock.AsyncMock(side_effect=ValueError("Invalid retention days"))
            response = await client.put(
                "/api/admin/retention",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"days": -1}
            )
            assert response.status_code == 400
            assert "invalid" in response.json()["detail"].lower()


class TestWorkspaceBulkActionException:
    """POST /workspaces/bulk-action exception catch."""

    @pytest.mark.asyncio
    async def test_workspace_bulk_exception(self, client, admin_token, test_user, db_session):
        ws_id = "11111111-1111-1111-1111-111111111111"
        with mock.patch("app.api.admin.WorkspaceService") as mock_service:
            instance = mock_service.return_value
            instance.delete_workspace = mock.AsyncMock(side_effect=RuntimeError("boom"))
            response = await client.post(
                "/api/admin/workspaces/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "delete", "workspace_ids": [ws_id]}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]["failed"]) == 1


class TestVolumeBulkActionException:
    """POST /volumes/bulk-action exception catch."""

    @pytest.mark.asyncio
    async def test_volume_bulk_exception(self, client, admin_token, test_user, db_session):
        vol_id = "11111111-1111-1111-1111-111111111111"
        with mock.patch("app.api.admin.VolumeService") as mock_service:
            instance = mock_service.return_value
            instance.delete_volume = mock.AsyncMock(side_effect=RuntimeError("boom"))
            response = await client.post(
                "/api/admin/volumes/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "delete", "volume_ids": [vol_id]}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]["failed"]) == 1


class TestPermissionsALL:
    """PUT /permissions/{role} with Permission.ALL in list."""

    @pytest.mark.asyncio
    async def test_update_role_with_all_permission(self, client, superadmin_token):
        from app.core.permissions import Permission
        response = await client.put(
            "/api/admin/permissions/admin",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={"permissions": [Permission.ALL, Permission.USERS_READ]}
        )
        assert response.status_code == 200


class TestHealthMonitoringFilters:
    """GET /health/monitoring filter branches."""

    @pytest.mark.asyncio
    async def test_health_monitoring_search_filter(self, client, admin_token, test_user, db_session):
        server = Server(name="searchable-server", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            "/api/admin/health/monitoring?search=searchable",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "system" in data
        assert "containers" in data

    @pytest.mark.asyncio
    async def test_health_monitoring_status_filter(self, client, admin_token, test_user, db_session):
        server = Server(name="status-server", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        hc = HealthCheck(
            server_id=server.id,
            container_id="c1",
            status="healthy",
            output="ok",
            checked_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(hc)
        await db_session.commit()

        response = await client.get(
            "/api/admin/health/monitoring?status=healthy",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "system" in data

    @pytest.mark.asyncio
    async def test_health_monitoring_recent_restarts(self, client, admin_token, test_user, db_session):
        server = Server(name="restart-server", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        hc = HealthCheck(
            server_id=server.id,
            container_id="c1",
            status="restarting",
            output="restarting...",
            checked_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(hc)
        await db_session.commit()

        response = await client.get(
            "/api/admin/health/monitoring",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["recent_restarts"]) >= 1
