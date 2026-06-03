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


class TestAdminStats:
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


class TestAdminUserManagement:
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


class TestAdminServerManagement:
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


class TestAdminPermissions:
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


class TestAdminEmail:
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


class TestAdminWorkspaceManagement:
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


class TestAdminVolumeManagement:
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


class TestAdminRetention:
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


class TestAdminHealthMonitoring:
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
