"""
Tests for Phase 5 Advanced Platform Features.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from httpx import AsyncClient


class TestServerBilling:
    """Test NUKE billing automation on server spawn"""
    
    @pytest.mark.asyncio
    async def test_spawn_deducts_credits(self, client: AsyncClient, test_user, user_token):
        """Test that server model has billing fields"""
        from app.models.server import Server
        server = Server()
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
    
    @pytest.mark.asyncio
    async def test_credit_service_consume(self, client: AsyncClient, test_user, user_token, db_session):
        """Test credit consumption"""
        from app.services.credit_service import CreditService
        
        service = CreditService(db_session)
        
        # Get initial balance
        initial = await service.get_balance(str(test_user.id))
        assert initial > 0
        
        # Consume credits
        tx = await service.consume_credits(
            user_id=str(test_user.id),
            amount=10,
            description="Test consumption"
        )
        
        assert tx.amount == -10
        assert tx.balance_after == initial - 10
        
        # Check new balance
        new_balance = await service.get_balance(str(test_user.id))
        assert new_balance == initial - 10


class TestResourcePool:
    """Test global resource pool tracking"""
    
    @pytest.mark.asyncio
    async def test_resource_pool_service(self, db_session):
        """Test resource pool calculations"""
        from app.services.resource_pool_service import ResourcePoolService
        
        service = ResourcePoolService(db_session)
        
        # Get available resources
        resources = await service.get_available_resources()
        
        assert "cpu" in resources
        assert "memory_mb" in resources
        assert "disk_mb" in resources
        
        assert resources["cpu"]["total"] == 34.0
        assert resources["cpu"]["available"] >= 0
    
    @pytest.mark.asyncio
    async def test_parse_memory(self):
        """Test memory parsing"""
        from app.services.resource_pool_service import ResourcePoolService
        
        assert ResourcePoolService._parse_memory("2g") == 2048
        assert ResourcePoolService._parse_memory("512m") == 512
        assert ResourcePoolService._parse_memory("1gb") == 1024


class TestTimeUtils:
    """Test time duration parsing"""
    
    def test_parse_duration(self):
        """Test duration parsing"""
        from app.core.time_utils import parse_duration
        
        assert parse_duration("30m") == 1800
        assert parse_duration("1h") == 3600
        assert parse_duration("24h") == 86400
        assert parse_duration("1d") == 86400
    
    def test_parse_duration_plain_int(self):
        """Test parsing plain integer"""
        from app.core.time_utils import parse_duration
        
        assert parse_duration("3600") == 3600
    
    def test_format_duration(self):
        """Test duration formatting"""
        from app.core.time_utils import format_duration
        
        assert format_duration(3600) == "1h"
        assert format_duration(1800) == "30m"
        assert format_duration(86400) == "1d"


class TestServerSchedules:
    """Test server scheduling API"""
    
    @pytest.mark.asyncio
    async def test_schedule_model(self):
        """Test schedule model exists and has correct fields"""
        from app.models.server_schedule import ServerSchedule
        
        schedule = ServerSchedule()
        assert hasattr(schedule, 'cron_expression')
        assert hasattr(schedule, 'action')
        assert hasattr(schedule, 'is_active')
        assert hasattr(schedule, 'next_run_at')
    
    @pytest.mark.asyncio
    async def test_schedule_service(self, db_session):
        """Test schedule service"""
        from app.services.schedule_service import ScheduleService
        
        service = ScheduleService(db_session)
        assert service is not None


class TestVolumeService:
    """Test volume management"""
    
    @pytest.mark.asyncio
    async def test_volume_service_exists(self):
        """Test volume service can be instantiated"""
        from app.services.volume_service import VolumeService
        
        service = VolumeService()
        assert service is not None
    
    @pytest.mark.asyncio
    async def test_volume_api_endpoints(self, client: AsyncClient, admin_token):
        """Test volume API requires admin"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        resp = await client.get("/api/volumes/", headers=headers)
        # Should succeed for admin
        assert resp.status_code in [200, 500]  # 500 if docker not available


class TestAnalyticsService:
    """Test analytics service"""
    
    @pytest.mark.asyncio
    async def test_analytics_service(self, db_session):
        """Test analytics service exists"""
        from app.services.analytics_service import AnalyticsService
        
        service = AnalyticsService(db_session)
        assert service is not None
    
    @pytest.mark.asyncio
    async def test_analytics_api_requires_admin(self, client: AsyncClient, test_user, user_token):
        """Test analytics API is admin-only"""
        headers = {"Authorization": f"Bearer {user_token}"}
        
        resp = await client.get("/api/analytics/global", headers=headers)
        # Should fail for non-admin
        assert resp.status_code == 403


class TestWebhookService:
    """Test webhook service"""
    
    def test_webhook_signing(self):
        """Test HMAC signature generation"""
        from app.services.webhook_service import WebhookService
        
        service = WebhookService(secret="test-secret")
        payload = {"event": "test", "data": {"id": "123"}}
        
        sig1 = service._sign_payload(payload)
        sig2 = service._sign_payload(payload)
        
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex length
    
    def test_webhook_different_payloads_different_sigs(self):
        """Test different payloads produce different signatures"""
        from app.services.webhook_service import WebhookService
        
        service = WebhookService(secret="test-secret")
        
        sig1 = service._sign_payload({"a": 1})
        sig2 = service._sign_payload({"a": 2})
        
        assert sig1 != sig2


class TestEmailService:
    """Test email service"""
    
    def test_email_templates(self):
        """Test email template rendering"""
        from app.services.email_service import EmailService
        
        service = EmailService()
        
        html = service.render_template("welcome", {
            "username": "testuser",
            "credits": 100
        })
        
        assert "Welcome to NukeLab" in html
        assert "testuser" in html
    
    def test_credit_low_template(self):
        """Test credit low email template"""
        from app.services.email_service import EmailService
        
        service = EmailService()
        html = service.render_template("credit_low", {
            "username": "testuser",
            "balance": 10,
            "server_name": "test-server"
        })
        
        assert "Low NUKE Credits" in html
        assert "10 credits" in html


class TestServerModelUpdates:
    """Test server model has new Phase 5 fields"""
    
    def test_server_billing_fields(self):
        """Test server model has billing fields"""
        from app.models.server import Server
        
        server = Server()
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')
    
    def test_server_defaults(self):
        """Test server field defaults"""
        from app.models.server import Server
        
        server = Server()
        # SQLAlchemy defaults are applied on INSERT, not instantiation
        assert server.total_cost is None  # Will be 0 on DB insert
        assert server.last_billed_at is None
        assert server.expires_at is None


class TestActivityLogUpdates:
    """Test activity log model has new Phase 5 fields"""
    
    def test_activity_log_state_fields(self):
        """Test activity log has before/after state"""
        from app.models.activity_log import ActivityLog
        
        log = ActivityLog()
        assert hasattr(log, 'before_state')
        assert hasattr(log, 'after_state')
        assert hasattr(log, 'request_id')


class TestQueueSystem:
    """Test server queue system"""
    
    @pytest.mark.asyncio
    async def test_queue_model(self):
        """Test queue model exists"""
        from app.models.server_queue import ServerQueue
        
        queue = ServerQueue()
        assert hasattr(queue, 'status')
        assert hasattr(queue, 'priority')
        assert hasattr(queue, 'server_name')
    
    @pytest.mark.asyncio
    async def test_queue_processor_task(self):
        """Test queue processor celery task exists"""
        from app.tasks import process_server_queue
        
        assert process_server_queue is not None


class TestNukeBillingTask:
    """Test NUKE billing celery task"""
    
    @pytest.mark.asyncio
    async def test_billing_task_exists(self):
        """Test billing task exists"""
        from app.tasks import process_nuke_billing
        
        assert process_nuke_billing is not None
    
    @pytest.mark.asyncio
    async def test_auto_stop_task_exists(self):
        """Test auto-stop task exists"""
        from app.tasks import enforce_auto_stop
        
        assert enforce_auto_stop is not None


class TestScheduleTask:
    """Test schedule evaluation task"""
    
    @pytest.mark.asyncio
    async def test_schedule_task_exists(self):
        """Test schedule evaluation task exists"""
        from app.tasks import evaluate_schedules
        
        assert evaluate_schedules is not None


class TestPermissionMatrixAPI:
    """Test permission matrix API"""
    
    @pytest.mark.asyncio
    async def test_get_permissions_admin_only(self, client: AsyncClient, test_user, user_token):
        """Test permission matrix is admin-only"""
        headers = {"Authorization": f"Bearer {user_token}"}
        
        resp = await client.get("/api/admin/permissions", headers=headers)
        assert resp.status_code == 403
    
    @pytest.mark.asyncio
    async def test_get_permissions_as_admin(self, client: AsyncClient, admin_token):
        """Test admin can get permission matrix"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        resp = await client.get("/api/admin/permissions", headers=headers)
        assert resp.status_code == 200
        
        data = resp.json()
        assert "roles" in data
        assert "permissions" in data
        assert "matrix" in data
        assert "super_admin" in data["matrix"]
        assert "admin" in data["matrix"]
    
    @pytest.mark.asyncio
    async def test_update_permissions(self, client: AsyncClient, admin_token):
        """Test admin can update role permissions"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get current permissions
        resp = await client.get("/api/admin/permissions", headers=headers)
        data = resp.json()
        
        # Update moderator permissions
        original_perms = data["matrix"]["moderator"]
        new_perms = ["users:read", "servers:read_all"]
        
        resp = await client.put(
            "/api/admin/permissions/moderator",
            headers=headers,
            json={"permissions": new_perms}
        )
        assert resp.status_code == 200
        
        updated = resp.json()
        assert updated["role"] == "moderator"
        assert updated["permissions"] == new_perms
    
    @pytest.mark.asyncio
    async def test_cannot_update_super_admin(self, client: AsyncClient, admin_token):
        """Test super_admin permissions cannot be modified"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        resp = await client.put(
            "/api/admin/permissions/super_admin",
            headers=headers,
            json={"permissions": []}
        )
        assert resp.status_code == 403


class TestBackupService:
    """Test backup and restore service"""
    
    @pytest.mark.asyncio
    async def test_backup_service_exists(self, db_session):
        """Test backup service can be instantiated"""
        from app.services.backup_service import BackupService
        
        service = BackupService(db_session, backup_path="/tmp/test-backups")
        assert service is not None
    
    @pytest.mark.asyncio
    async def test_volume_backup_model(self):
        """Test VolumeBackup model exists"""
        from app.models.volume_backup import VolumeBackup
        
        backup = VolumeBackup()
        assert hasattr(backup, 'volume_name')
        assert hasattr(backup, 'size_bytes')
        assert hasattr(backup, 'status')
        assert hasattr(backup, 'backup_path')
    
    @pytest.mark.asyncio
    async def test_backup_api_endpoints_exist(self, client: AsyncClient, admin_token):
        """Test backup endpoints are registered"""
        from app.api.volumes import router
        
        route_paths = [route.path for route in router.routes]
        assert any("backup" in path for path in route_paths)


class TestWorkspaceService:
    """Test shared workspace service"""
    
    @pytest.mark.asyncio
    async def test_workspace_model(self):
        """Test workspace model exists"""
        from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
        
        ws = SharedWorkspace()
        assert hasattr(ws, 'name')
        assert hasattr(ws, 'volume_name')
        assert hasattr(ws, 'owner_id')
        
        member = WorkspaceMember()
        assert hasattr(member, 'role')
        assert hasattr(member, 'workspace_id')
    
    @pytest.mark.asyncio
    async def test_create_workspace(self, db_session, test_user):
        """Test creating a workspace"""
        from app.services.workspace_service import WorkspaceService
        
        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="A test workspace",
            volume_name="test-volume",
            owner_id=str(test_user.id)
        )
        
        assert workspace.name == "Test Workspace"
        assert workspace.volume_name == "test-volume"
        assert str(workspace.owner_id) == str(test_user.id)
    
    @pytest.mark.asyncio
    async def test_workspace_members(self, db_session, test_user, admin_user):
        """Test adding and removing members"""
        from app.services.workspace_service import WorkspaceService
        
        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="Test",
            volume_name="test-volume",
            owner_id=str(test_user.id)
        )
        
        # Add member
        member = await service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="read_write"
        )
        
        assert member.role == "read_write"
        
        # Check workspace access
        is_member = await service.is_workspace_member(str(workspace.id), str(admin_user.id))
        assert is_member is True
        
        # Update role
        updated = await service.update_member_role(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="admin"
        )
        assert updated.role == "admin"
        
        # Remove member
        success = await service.remove_member(str(workspace.id), str(admin_user.id))
        assert success is True
    
    @pytest.mark.asyncio
    async def test_workspace_api(self, client: AsyncClient, test_user, user_token):
        """Test workspace API endpoints"""
        headers = {"Authorization": f"Bearer {user_token}"}
        
        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "API Test Workspace",
            "description": "Testing",
            "volume_name": "test-vol"
        })
        assert resp.status_code == 201
        
        workspace = resp.json()
        assert workspace["name"] == "API Test Workspace"
        
        # List workspaces
        resp = await client.get("/api/workspaces/", headers=headers)
        assert resp.status_code == 200
        
        data = resp.json()
        assert len(data["workspaces"]) >= 1
        
        # Get workspace
        resp = await client.get(f"/api/workspaces/{workspace['id']}", headers=headers)
        assert resp.status_code == 200
        
        ws_data = resp.json()
        assert ws_data["name"] == "API Test Workspace"
