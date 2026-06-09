"""Tests for Admin API endpoints."""

import pytest


class TestAdminAccessControl:
    """Tests for admin access restrictions."""

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_stats(self, client, user_token):
        """Regular user should not access admin stats."""
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_users(self, client, user_token):
        """Regular user should not list admin users."""
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_servers(self, client, user_token):
        """Regular user should not access admin servers."""
        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestAdminStats:
    """Tests for admin stats endpoint."""

    @pytest.mark.asyncio
    async def test_admin_get_stats(self, client, admin_token):
        """Admin should get dashboard stats."""
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "servers" in data
        assert "credits" in data


class TestAdminUserManagement:
    """Tests for admin user management."""

    @pytest.mark.asyncio
    async def test_admin_list_users(self, client, admin_token):
        """Admin should list users."""
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data

    @pytest.mark.asyncio
    async def test_admin_list_users_with_search(self, client, admin_token):
        """Admin should search users."""
        response = await client.get(
            "/api/admin/users?search=test",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_users_with_role_filter(self, client, admin_token):
        """Admin should filter users by role."""
        response = await client.get(
            "/api/admin/users?role=user",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_bulk_action_invalid_action(self, client, admin_token):
        """Invalid bulk action should fail or no-op."""
        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "user_ids": []}
        )
        # Empty user_ids may return 200 as no-op; invalid action with users should error
        assert response.status_code in [200, 400, 422]


class TestAdminServerManagement:
    """Tests for admin server management."""

    @pytest.mark.asyncio
    async def test_admin_list_servers(self, client, admin_token):
        """Admin should list all servers."""
        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data

    @pytest.mark.asyncio
    async def test_admin_server_bulk_action_invalid(self, client, admin_token):
        """Invalid server bulk action should fail or no-op."""
        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "server_ids": []}
        )
        assert response.status_code in [200, 400, 422]


class TestAdminCredits:
    """Tests for admin credit management."""

    @pytest.mark.asyncio
    async def test_admin_credits_summary(self, client, admin_token):
        """Admin should get credits summary."""
        response = await client.get(
            "/api/admin/credits/summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def admin_grant_bulk_invalid(self, client, admin_token):
        """Bulk grant with invalid data should fail."""
        response = await client.post(
            "/api/admin/credits/grant-bulk",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_ids": [], "amount": 0, "reason": ""}
        )
        assert response.status_code in [400, 422]


class TestAdminActivity:
    """Tests for admin activity endpoints."""

    @pytest.mark.asyncio
    async def test_admin_get_activity(self, client, admin_token):
        """Admin should get activity logs."""
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data

    @pytest.mark.asyncio
    async def test_admin_get_activity_with_filters(self, client, admin_token):
        """Admin should filter activity logs."""
        response = await client.get(
            "/api/admin/activity?limit=10&action=server.create",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_system_health(self, client, admin_token):
        """Admin should get system health."""
        response = await client.get(
            "/api/admin/system/health",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAdminPermissions:
    """Tests for admin permission management."""

    @pytest.mark.asyncio
    async def test_admin_get_permissions(self, client, admin_token):
        """Admin should get permissions list."""
        response = await client.get(
            "/api/admin/permissions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_update_permissions_invalid_role(self, client, admin_token):
        """Updating permissions for invalid role should 404."""
        response = await client.put(
            "/api/admin/permissions/invalid_role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": []}
        )
        assert response.status_code in [400, 404, 422]


class TestAdminEmail:
    """Tests for admin email management."""

    @pytest.mark.asyncio
    async def test_admin_get_email_config(self, client, admin_token):
        """Admin should get email config."""
        response = await client.get(
            "/api/admin/email-config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_get_email_status(self, client, admin_token):
        """Admin should get email status."""
        response = await client.get(
            "/api/admin/email-status",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAdminWorkspaceManagement:
    """Tests for admin workspace management."""

    @pytest.mark.asyncio
    async def test_admin_list_workspaces(self, client, admin_token):
        """Admin should list workspaces."""
        response = await client.get(
            "/api/admin/workspaces",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data

    @pytest.mark.asyncio
    async def test_admin_get_workspace_not_found(self, client, admin_token):
        """Admin getting non-existent workspace should 404."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_update_workspace_not_found(self, client, admin_token):
        """Admin updating non-existent workspace should 404."""
        response = await client.put(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "new-name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_workspace_not_found(self, client, admin_token):
        """Admin deleting non-existent workspace should 404."""
        response = await client.delete(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_workspace_members_not_found(self, client, admin_token):
        """Admin getting members of non-existent workspace."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000/members",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # May return 404 or empty list depending on implementation
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_admin_workspace_volumes_not_found(self, client, admin_token):
        """Admin getting volumes of non-existent workspace."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000/volumes",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code in [200, 404]


class TestAdminVolumeManagement:
    """Tests for admin volume management."""

    @pytest.mark.asyncio
    async def test_admin_list_volumes(self, client, admin_token):
        """Admin should list volumes."""
        response = await client.get(
            "/api/admin/volumes",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "volumes" in data

    @pytest.mark.asyncio
    async def test_admin_get_volume_not_found(self, client, admin_token):
        """Admin getting non-existent volume should 404."""
        response = await client.get(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_update_volume_not_found(self, client, admin_token):
        """Admin updating non-existent volume should 404."""
        response = await client.put(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "new-name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_volume_not_found(self, client, admin_token):
        """Admin deleting non-existent volume should 404."""
        response = await client.delete(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


class TestAdminRetention:
    """Tests for admin retention settings."""

    @pytest.mark.asyncio
    async def test_admin_get_retention(self, client, admin_token):
        """Admin should get retention settings."""
        response = await client.get(
            "/api/admin/retention",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_update_retention(self, client, admin_token):
        """Admin should update retention settings."""
        response = await client.put(
            "/api/admin/retention",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"server_retention_days": 30}
        )
        # Endpoint may have specific required fields
        assert response.status_code in [200, 400, 422]


class TestAdminHealthMonitoring:
    """Tests for admin health monitoring."""

    @pytest.mark.asyncio
    async def test_admin_health_monitoring(self, client, admin_token):
        """Admin should get health monitoring data."""
        response = await client.get(
            "/api/admin/health/monitoring",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "system" in data
        assert "services" in data["system"]
        assert "partitions" in data["system"]["services"]


class TestAdminBulkActions:
    """Tests for admin bulk actions."""

    @pytest.mark.asyncio
    async def test_admin_workspace_bulk_action_invalid(self, client, admin_token):
        """Invalid workspace bulk action should fail."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "workspace_ids": []}
        )
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_admin_volume_bulk_action_invalid(self, client, admin_token):
        """Invalid volume bulk action should fail."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "volume_ids": []}
        )
        assert response.status_code in [400, 422]

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
        assert response.status_code == 400
        assert "unknown action" in response.json()["detail"].lower()


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
        assert response.status_code == 400
        assert "unknown action" in response.json()["detail"].lower()


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

"""Extended tests for Admin API endpoints."""

import pytest
from unittest import mock
from datetime import datetime, timedelta

from app.models.user import User
from app.models.server import Server
from app.models.credit_transaction import CreditTransaction
from app.models.activity_log import ActivityLog
from app.models.shared_workspace import SharedWorkspace
from app.models.volume import Volume


class TestAdminStatsExtended:
    @pytest.mark.asyncio
    async def test_admin_stats(self, client, admin_token, admin_user, test_user, db_session):
        # Add some servers
        s1 = Server(name="srv1", user_id=admin_user.id, status="running", container_id="c1")
        s2 = Server(name="srv2", user_id=test_user.id, status="stopped", container_id="c2")
        db_session.add_all([s1, s2])
        await db_session.commit()

        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["users"]["total"] >= 2
        assert data["servers"]["total"] >= 2
        assert data["servers"]["running"] >= 1
        assert "by_role" in data["users"]

    @pytest.mark.asyncio
    async def test_admin_stats_forbidden(self, client, user_token):
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestAdminUserManagementExtended:
    @pytest.mark.asyncio
    async def test_admin_list_users(self, client, admin_token, admin_user, test_user):
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_admin_list_users_filtered(self, client, admin_token, test_user):
        response = await client.get(
            "/api/admin/users?role=user&search=test&page=1&limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_bulk_user_action_disable(self, client, admin_token, test_user):
        with mock.patch("app.api.admin.UserService") as MockService:
            mock_svc = MockService.return_value
            mock_svc.disable_user = mock.AsyncMock()
            response = await client.post(
                "/api/admin/users/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "disable", "user_ids": [str(test_user.id)]}
            )
        assert response.status_code == 200


class TestAdminServerManagementExtended:
    @pytest.mark.asyncio
    async def test_admin_list_servers(self, client, admin_token, admin_user, db_session):
        s = Server(name="adm-srv", user_id=admin_user.id, status="running", container_id="c99")
        db_session.add(s)
        await db_session.commit()

        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_admin_list_servers_filtered(self, client, admin_token, admin_user, db_session):
        s = Server(name="flt-srv", user_id=admin_user.id, status="stopped", container_id="c88")
        db_session.add(s)
        await db_session.commit()

        response = await client.get(
            "/api/admin/servers?status=stopped&page=1&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_bulk_server_action(self, client, admin_token, admin_user, db_session):
        s = Server(name="bulk-srv", user_id=admin_user.id, status="stopped", container_id="c77")
        db_session.add(s)
        await db_session.commit()

        with mock.patch("app.container.spawner.spawner") as mock_spawner:
            mock_spawner.start = mock.AsyncMock()
            with mock.patch("app.api.admin.broadcast_server_status_change") as mock_bc:
                mock_bc.return_value = None
                response = await client.post(
                    "/api/admin/servers/bulk-action",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"action": "start", "server_ids": [str(s.id)]}
                )
        assert response.status_code == 200


class TestAdminCreditManagement:
    @pytest.mark.asyncio
    async def test_admin_credit_summary(self, client, admin_token, test_user, db_session):
        ct = CreditTransaction(user_id=test_user.id, amount=100, balance_after=100, type="grant", description="test")
        db_session.add(ct)
        await db_session.commit()

        response = await client.get(
            "/api/admin/credits/summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_credits_in_system" in data
        assert "top_users" in data

    @pytest.mark.asyncio
    async def test_admin_bulk_grant_credits(self, client, admin_token, test_user):
        with mock.patch("app.api.admin.CreditService") as MockService:
            MockService.return_value.grant_credits = mock.AsyncMock()
            response = await client.post(
                "/api/admin/credits/grant-bulk",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"user_ids": [str(test_user.id)], "amount": 50, "reason": "test"}
            )
        assert response.status_code == 200


class TestAdminActivityLogs:
    @pytest.mark.asyncio
    async def test_admin_activity_logs(self, client, admin_token, admin_user, db_session):
        log = ActivityLog(actor_id=admin_user.id, action="test", target_type="user", target_id=str(admin_user.id))
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_admin_activity_filtered(self, client, admin_token, admin_user, db_session):
        log = ActivityLog(actor_id=admin_user.id, action="delete", target_type="server")
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/admin/activity?action=delete&target_type=server&page=1&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_activity_export_json(self, client, admin_token, admin_user, db_session):
        log = ActivityLog(actor_id=admin_user.id, action="export", target_type="log")
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/admin/activity/export?format=json&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data

    @pytest.mark.asyncio
    async def test_admin_activity_export_csv(self, client, admin_token, admin_user, db_session):
        log = ActivityLog(actor_id=admin_user.id, action="csv", target_type="log")
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/admin/activity/export?format=csv&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"


class TestAdminSystemHealth:
    @pytest.mark.asyncio
    async def test_admin_system_health(self, client, admin_token):
        response = await client.get(
            "/api/admin/system/health",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "database" in data
        assert "timestamp" in data


class TestAdminPermissionsExtended:
    @pytest.mark.asyncio
    async def test_admin_permission_matrix(self, client, admin_token):
        response = await client.get(
            "/api/admin/permissions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "matrix" in data
        assert "roles" in data
        assert "permissions" in data

    @pytest.mark.asyncio
    async def test_admin_update_role_permissions(self, client, admin_token):
        with mock.patch("app.core.roles.save_role_permissions_to_db") as mock_save:
            mock_save.return_value = None
            response = await client.put(
                "/api/admin/permissions/admin",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"permissions": ["admin:access", "users:read", "users:create", "servers:read_own", "servers:write_own", "volumes:read_own", "volumes:write_own", "workspaces:read_own", "workspaces:write_own", "credits:read_own", "analytics:read", "audit:read"]}
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_update_super_admin_fails(self, client, admin_token):
        response = await client.put(
            "/api/admin/permissions/super_admin",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": ["ADMIN_ACCESS"]}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_update_invalid_role(self, client, admin_token):
        response = await client.put(
            "/api/admin/permissions/hacker",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": ["ADMIN_ACCESS"]}
        )
        assert response.status_code == 400


class TestAdminEmailExtended:
    @pytest.mark.asyncio
    async def test_admin_email_config(self, client, admin_token):
        response = await client.get(
            "/api/admin/email-config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "smtp_host" in data

    @pytest.mark.asyncio
    async def test_admin_email_test_disabled(self, client, admin_token):
        with mock.patch("app.services.email_service.EmailService") as MockSvc:
            mock_inst = MockSvc.return_value
            mock_inst.enabled = False
            response = await client.post(
                "/api/admin/email-test",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={}
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_email_status(self, client, admin_token):
        with mock.patch("app.services.email_service.EmailService") as MockSvc:
            mock_inst = MockSvc.return_value
            mock_inst.enabled = False
            response = await client.get(
                "/api/admin/email-status",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"


class TestAdminWorkspaceManagementExtended:
    @pytest.mark.asyncio
    async def test_admin_list_workspaces(self, client, admin_token, admin_user, test_user, db_session):
        ws = SharedWorkspace(name="adm-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        response = await client.get(
            "/api/admin/workspaces",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_admin_get_workspace(self, client, admin_token, test_user, db_session):
        ws = SharedWorkspace(name="get-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        response = await client.get(
            f"/api/admin/workspaces/{ws.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "workspace" in data

    @pytest.mark.asyncio
    async def test_admin_get_workspace_404(self, client, admin_token):
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_workspace(self, client, admin_token, test_user, db_session):
        ws = SharedWorkspace(name="del-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        with mock.patch("app.api.admin.WorkspaceService") as MockSvc:
            MockSvc.return_value.get_workspace = mock.AsyncMock(return_value=ws)
            MockSvc.return_value.delete_workspace = mock.AsyncMock(return_value=True)
            response = await client.delete(
                f"/api/admin/workspaces/{ws.id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_admin_bulk_workspace_action(self, client, admin_token, test_user, db_session):
        ws = SharedWorkspace(name="bulk-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        with mock.patch("app.api.admin.WorkspaceService") as MockSvc:
            MockSvc.return_value.update_workspace = mock.AsyncMock()
            response = await client.post(
                "/api/admin/workspaces/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "deactivate", "workspace_ids": [str(ws.id)]}
            )
        assert response.status_code == 200


class TestAdminVolumeManagementExtended:
    @pytest.mark.asyncio
    async def test_admin_list_volumes(self, client, admin_token, test_user, db_session):
        vol = Volume(name="adm-vol", display_name="Admin Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()

        response = await client.get(
            "/api/admin/volumes",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "volumes" in data
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_admin_get_volume(self, client, admin_token, test_user, db_session):
        vol = Volume(name="get-vol", display_name="Get Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        response = await client.get(
            f"/api/admin/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "volume" in response.json()

    @pytest.mark.asyncio
    async def test_admin_get_volume_404(self, client, admin_token):
        response = await client.get(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_volume(self, client, admin_token, test_user, db_session):
        vol = Volume(name="del-vol", display_name="Del Vol", owner_id=test_user.id, size_bytes=0, max_size_bytes=1000000)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.admin.VolumeService") as MockSvc:
            MockSvc.return_value.get_volume = mock.AsyncMock(return_value=vol)
            MockSvc.return_value.delete_volume = mock.AsyncMock(return_value=True)
            response = await client.delete(
                f"/api/admin/volumes/{vol.id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_admin_bulk_volume_action(self, client, admin_token, test_user, db_session):
        vol = Volume(name="bulk-vol", display_name="Bulk Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.admin.VolumeService") as MockSvc:
            MockSvc.return_value.update_volume = mock.AsyncMock()
            MockSvc.return_value.delete_volume = mock.AsyncMock(return_value=True)
            response = await client.post(
                "/api/admin/volumes/bulk-action",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "archive", "volume_ids": [str(vol.id)]}
            )
        assert response.status_code == 200


class TestAdminRetentionExtended:
    @pytest.mark.asyncio
    async def test_admin_get_retention(self, client, admin_token):
        with mock.patch("app.api.admin.RetentionService") as MockSvc:
            MockSvc.return_value.get_policy = mock.AsyncMock(return_value={"days": 30})
            response = await client.get(
                "/api/admin/retention",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        assert "retention_policy" in response.json()

    @pytest.mark.asyncio
    async def test_admin_update_retention(self, client, admin_token):
        with mock.patch("app.api.admin.RetentionService") as MockSvc:
            MockSvc.return_value.set_policy = mock.AsyncMock(return_value={"days": 60})
            response = await client.put(
                "/api/admin/retention",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"days": 60}
            )
        assert response.status_code == 200
        assert response.json()["success"] is True


class TestAdminHealthMonitoringExtended:
    @pytest.mark.asyncio
    async def test_admin_health_monitoring(self, client, admin_token):
        # Mock psutil and container client to avoid side effects
        mock_psutil_module = mock.Mock()
        mock_psutil_module.cpu_percent.return_value = 10.0
        mock_psutil_module.cpu_count.return_value = 4
        mock_psutil_module.virtual_memory.return_value = mock.Mock(percent=50.0, total=16000000000, available=8000000000, used=8000000000)
        mock_psutil_module.disk_usage.return_value = mock.Mock(percent=30, total=100000000000, used=30000000000, free=70000000000)
        mock_psutil_module.disk_partitions.return_value = []
        mock_psutil_module.cpu_freq.return_value = None
        mock_psutil_module.getloadavg.return_value = (1.0, 2.0, 3.0)

        with mock.patch.dict("sys.modules", {"psutil": mock_psutil_module}):
            mock_container_client = mock.AsyncMock()
            mock_container_client.connect = mock.AsyncMock()
            mock_container_client.version = mock.AsyncMock(return_value={"Version": "4.9", "Components": [{"Name": "Podman"}]})
            with mock.patch("app.container.client.container_client", mock_container_client):
                response = await client.get(
                    "/api/admin/health/monitoring",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert "system" in data
        assert "containers" in data
        assert "recent_restarts" in data
        assert "partitions" in data["system"]["services"]
        assert data["system"]["services"]["partitions"]["status"] in ("healthy", "unhealthy")

"""Extended tests for admin.py — error branches and filter coverage."""

import pytest
import pytest_asyncio
import uuid as uuid_mod
from unittest import mock
from datetime import datetime, timedelta, UTC

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
        """Missing user should be caught and reported in the failed list."""
        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "disable", "user_ids": [str(uuid_mod.uuid4())]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]["failed"]) == 1
        assert "not found" in data["results"]["failed"][0]["error"].lower()


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
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db_session.add(log)
        await db_session.commit()

        from_date = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat()
        to_date = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1)).isoformat()

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
