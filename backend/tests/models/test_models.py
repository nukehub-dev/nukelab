"""Coverage tests for model to_dict and property methods (in-memory, no DB)."""

import pytest
import uuid
from datetime import datetime, UTC


class TestActivityLogModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.activity_log import ActivityLog
        log = ActivityLog(
            actor_id=uuid.uuid4(), action="test",
            target_type="server", target_id=str(uuid.uuid4()), details={}
        )
        d = log.to_dict()
        assert d["action"] == "test"


class TestAlertHistoryModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.alert_history import AlertHistory
        ah = AlertHistory(rule_id=uuid.uuid4(), metric_value=1.0, threshold=0.5, status="firing")
        d = ah.to_dict()
        assert d["metric_value"] == 1.0


class TestAlertRuleModel:
    @pytest.mark.asyncio
    async def test_evaluate_and_to_dict(self):
        from app.models.alert_rule import AlertRule
        rule = AlertRule(
            name="cpu", metric_type="cpu_percent",
            operator=">", threshold=80.0, scope="global"
        )
        assert rule.evaluate(85.0) is True
        assert rule.evaluate(75.0) is False
        d = rule.to_dict()
        assert d["name"] == "cpu"


class TestApiTokenModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.api_token import ApiToken
        token = ApiToken(
            user_id=uuid.uuid4(), name="test",
            token_prefix="pref", token_hash="hash"
        )
        d = token.to_dict()
        assert d["name"] == "test"
        assert "token_hash" not in d
        d2 = token.to_dict(include_hash=True)
        assert "token_hash" in d2


class TestCreditTransactionModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.credit_transaction import CreditTransaction
        ct = CreditTransaction(user_id=uuid.uuid4(), amount=10, type="grant")
        d = ct.to_dict()
        assert d["amount"] == 10


class TestDailyServerMetricModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.daily_server_metric import DailyServerMetric
        from datetime import date
        dm = DailyServerMetric(server_id=uuid.uuid4(), date=date.today())
        d = dm.to_dict()
        assert "server_id" in d


class TestEnvironmentTemplateModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.environment_template import EnvironmentTemplate
        et = EnvironmentTemplate(name="Test", slug="test", image="test:latest")
        d = et.to_dict()
        assert d["slug"] == "test"


class TestHealthCheckModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.health_check import HealthCheck
        hc = HealthCheck(server_id=uuid.uuid4(), status="healthy")
        d = hc.to_dict()
        assert d["status"] == "healthy"


class TestIpRestrictionModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.ip_restriction import IPRestriction
        ipr = IPRestriction(ip_range="192.168.1.0/24", restriction_type="allow")
        d = ipr.to_dict()
        assert d["ip_range"] == "192.168.1.0/24"


class TestMaintenanceWindowModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.maintenance_window import MaintenanceWindow
        mw = MaintenanceWindow(
            title="Test", message="msg",
            start_at=datetime.now(UTC).replace(tzinfo=None), end_at=datetime.now(UTC).replace(tzinfo=None),
            created_by="admin"
        )
        d = mw.to_dict()
        assert d["title"] == "Test"


class TestNotificationModel:
    @pytest.mark.asyncio
    async def test_repr_and_to_dict(self):
        from app.models.notification import Notification
        n = Notification(user_id=uuid.uuid4(), type="info", message="hello")
        assert "Notification" in repr(n)
        d = n.to_dict()
        assert d["message"] == "hello"


class TestPlanAccessModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.plan_access import UserPlanAccess, WorkspacePlanAccess
        pa = UserPlanAccess(user_id=uuid.uuid4(), plan_id=uuid.uuid4(), granted_by=uuid.uuid4())
        d = pa.to_dict()
        assert "user_id" in d
        wpa = WorkspacePlanAccess(workspace_id=uuid.uuid4(), plan_id=uuid.uuid4())
        d2 = wpa.to_dict()
        assert "workspace_id" in d2


class TestRefreshTokenModel:
    @pytest.mark.asyncio
    async def test_repr_and_to_dict(self):
        from app.models.refresh_token import RefreshToken
        rt = RefreshToken(user_id=uuid.uuid4(), token_hash="hash", token_lookup="look")
        assert "RefreshToken" in repr(rt)
        d = rt.to_dict()
        assert "user_id" in d


class TestResourceQuotaModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.resource_quota import ResourceQuota
        rq = ResourceQuota(user_id=uuid.uuid4())
        d = rq.to_dict()
        assert "user_id" in d


class TestServerMetricModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.server_metric import ServerMetric
        sm = ServerMetric(
            server_id=uuid.uuid4(), container_id="abc123", cpu_percent=50.0,
            memory_used=100, memory_total=200, memory_percent=50.0,
            disk_read_bytes=0, disk_write_bytes=0,
            network_rx_bytes=0, network_tx_bytes=0,
            pids=1
        )
        d = sm.to_dict()
        assert d["cpu"]["percent"] == 50.0


class TestServerPlanModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.server_plan import ServerPlan
        sp = ServerPlan(name="Test", slug="test", category="cpu")
        d = sp.to_dict()
        assert d["slug"] == "test"


class TestServerQueueModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.server_queue import ServerQueue
        sq = ServerQueue(
            user_id=uuid.uuid4(), plan_id=uuid.uuid4(),
            environment_id=uuid.uuid4(), server_name="test"
        )
        d = sq.to_dict()
        assert d["server_name"] == "test"


class TestServerScheduleModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.server_schedule import ServerSchedule
        ss = ServerSchedule(
            server_id=uuid.uuid4(),
            action="start", cron_expression="0 0 * * *"
        )
        d = ss.to_dict()
        assert d["action"] == "start"


class TestSystemMetricModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.system_metric import SystemMetric
        sm = SystemMetric(
            cpu_percent=10.0, memory_percent=20.0,
            disk_used=100, disk_total=200, disk_percent=50.0,
            disk_read_bytes=0, disk_write_bytes=0,
            network_rx_bytes=0, network_tx_bytes=0,
            docker_containers_running=0, docker_containers_total=0, docker_images_total=0
        )
        d = sm.to_dict()
        assert d["cpu"]["percent"] == 10.0


class TestSystemSettingModel:
    @pytest.mark.asyncio
    async def test_repr(self):
        from app.models.system_setting import SystemSetting
        ss = SystemSetting(key="test_key", value="test_value")
        assert "test_key" in repr(ss)


class TestUserModel:
    @pytest.mark.asyncio
    async def test_display_name_and_avatar(self):
        from app.models.user import User
        user = User(
            username="testname", email="t@example.com",
            first_name="John", last_name="Doe"
        )
        assert user.display_name == "John Doe"
        assert "gravatar" in user.get_gravatar_url()
        # Without use_gravatar pref or avatar_url, get_avatar_url returns ""
        assert user.get_avatar_url() == ""
        d = user.to_dict()
        assert d["username"] == "testname"

    @pytest.mark.asyncio
    async def test_display_name_fallback(self):
        from app.models.user import User
        user = User(username="noname", email="n@example.com")
        assert user.display_name == "noname"

    @pytest.mark.asyncio
    async def test_avatar_url_custom(self):
        from app.models.user import User
        user = User(username="avatar", email="a@example.com", avatar_url="http://custom.com/ava.png")
        assert user.get_avatar_url() == "http://custom.com/ava.png"


class TestVolumeModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.volume import Volume
        vol = Volume(name="test", display_name="Test Vol", owner_id=uuid.uuid4(), size_bytes=1024)
        d = vol.to_dict()
        assert d["name"] == "test"


class TestVolumeBackupModel:
    @pytest.mark.asyncio
    async def test_repr(self):
        from app.models.volume_backup import VolumeBackup
        vb = VolumeBackup(volume_name="testvol", backup_path="/backups/test")
        assert "VolumeBackup" in repr(vb)


class TestWorkspaceInvitationModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.workspace_invitation import WorkspaceInvitation
        wi = WorkspaceInvitation(
            workspace_id=uuid.uuid4(),
            invited_by=uuid.uuid4(), user_id=uuid.uuid4(), role="member"
        )
        d = wi.to_dict()
        assert d["role"] == "member"


class TestWorkspaceVolumeModel:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        from app.models.workspace_volume import WorkspaceVolume
        wv = WorkspaceVolume(workspace_id=uuid.uuid4(), volume_id=uuid.uuid4())
        d = wv.to_dict()
        assert "workspace_id" in d
