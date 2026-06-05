"""Coverage-focused tests for utility modules and easy wins."""

import pytest
from unittest import mock
from cryptography.fernet import InvalidToken


class TestTimeUtils:
    """app/core/time_utils.py coverage."""

    @pytest.mark.asyncio
    async def test_parse_duration_seconds(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("30") == 30
        assert parse_duration("30s") == 30

    @pytest.mark.asyncio
    async def test_parse_duration_minutes(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("30m") == 1800

    @pytest.mark.asyncio
    async def test_parse_duration_hours(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("1h") == 3600
        assert parse_duration("24h") == 86400

    @pytest.mark.asyncio
    async def test_parse_duration_days(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("1d") == 86400

    @pytest.mark.asyncio
    async def test_parse_duration_weeks(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("1w") == 604800

    @pytest.mark.asyncio
    async def test_parse_duration_empty(self):
        from app.core.time_utils import parse_duration
        assert parse_duration("") == 0
        assert parse_duration(None) == 0

    @pytest.mark.asyncio
    async def test_parse_duration_invalid(self):
        from app.core.time_utils import parse_duration
        with pytest.raises(ValueError):
            parse_duration("invalid")

    @pytest.mark.asyncio
    async def test_format_duration(self):
        from app.core.time_utils import format_duration
        assert format_duration(30) == "30s"
        assert format_duration(120) == "2m"
        assert format_duration(3600) == "1h"
        assert format_duration(86400) == "1d"
        assert format_duration(604800) == "1w"


class TestTokenEncryption:
    """app/core/token_encryption.py coverage."""

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self):
        from app.core.token_encryption import encrypt_token, decrypt_token
        original = "my-secret-token"
        encrypted = encrypt_token(original)
        assert encrypted != original
        decrypted = decrypt_token(encrypted)
        assert decrypted == original

    @pytest.mark.asyncio
    async def test_encrypt_empty_returns_empty(self):
        from app.core.token_encryption import encrypt_token
        assert encrypt_token("") == ""
        assert encrypt_token(None) == ""

    @pytest.mark.asyncio
    async def test_decrypt_invalid_raises(self):
        from app.core.token_encryption import decrypt_token
        with pytest.raises(InvalidToken):
            decrypt_token("not-valid-base64!!!")

    @pytest.mark.asyncio
    async def test_decrypt_empty_returns_empty(self):
        from app.core.token_encryption import decrypt_token
        assert decrypt_token("") == ""
        assert decrypt_token(None) == ""


class TestDbSeed:
    """app/db/seed.py coverage."""

    @pytest.mark.asyncio
    async def test_seed_admin_user_dev_mode(self, db_session):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", "seedadmin"):
                with mock.patch("app.db.seed.settings.dev_admin_password", "seedpass"):
                    await seed_admin_user(db_session)
                    from app.models.user import User
                    result = await db_session.execute(
                        __import__('sqlalchemy').select(User).where(User.username == "seedadmin")
                    )
                    user = result.scalar_one_or_none()
                    assert user is not None
                    assert user.role == "admin"

    @pytest.mark.asyncio
    async def test_seed_admin_user_not_dev_mode(self, db_session):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", False):
            result = await seed_admin_user(db_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_seed_admin_user_already_exists(self, db_session, test_user):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", test_user.username):
                result = await seed_admin_user(db_session)
                assert result is None

    @pytest.mark.asyncio
    async def test_seed_plans(self, db_session):
        from app.db.seed import seed_plans
        await seed_plans(db_session)
        from app.models.server_plan import ServerPlan
        result = await db_session.execute(
            __import__('sqlalchemy').select(ServerPlan).where(ServerPlan.slug == "small")
        )
        plan = result.scalar_one_or_none()
        assert plan is not None

    @pytest.mark.asyncio
    async def test_seed_plans_idempotent(self, db_session):
        from app.db.seed import seed_plans
        await seed_plans(db_session)
        await seed_plans(db_session)


class TestTasks:
    """app/tasks.py coverage."""

    @pytest.mark.asyncio
    async def test_example_task(self):
        from app.tasks import example_task
        result = example_task.run(message="hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_cleanup_inactive_servers(self):
        from app.tasks import cleanup_inactive_servers
        result = cleanup_inactive_servers.run()
        assert "Cleanup completed" == result

    @pytest.mark.asyncio
    async def test_collect_container_metrics_error(self):
        from app.tasks import collect_container_metrics
        with mock.patch("app.tasks.MetricsCollector") as mock_collector:
            mock_collector.side_effect = Exception("fail")
            result = collect_container_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_collect_system_metrics_error(self):
        from app.tasks import collect_system_metrics
        with mock.patch("app.tasks.SystemMetricsCollector") as mock_collector:
            mock_collector.side_effect = Exception("fail")
            result = collect_system_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_check_container_health_error(self):
        from app.tasks import check_container_health
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = check_container_health.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_alert_rules_error(self):
        from app.tasks import evaluate_alert_rules
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_alert_rules.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_maintenance_windows_error(self):
        from app.tasks import evaluate_maintenance_windows
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_maintenance_windows.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_process_nuke_billing_error(self):
        from app.tasks import process_nuke_billing
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = process_nuke_billing.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_enforce_auto_stop_error(self):
        from app.tasks import enforce_auto_stop
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = enforce_auto_stop.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_process_server_queue_error(self):
        from app.tasks import process_server_queue
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = process_server_queue.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_schedules_error(self):
        from app.tasks import evaluate_schedules
        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_schedules.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_rollup_server_metrics_error(self):
        from app.tasks import rollup_server_metrics
        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = rollup_server_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_cleanup_expired_data_error(self):
        from app.tasks import cleanup_expired_data
        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = cleanup_expired_data.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_shutdown_idle_servers_error(self):
        from app.tasks import shutdown_idle_servers
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = shutdown_idle_servers.run()
            assert "Error" in result


class TestSecurityHeadersAsgi:
    """app/core/security_headers_asgi.py coverage."""

    @pytest.mark.asyncio
    async def test_security_headers_websocket_skipped(self):
        from app.core.security_headers_asgi import SecurityHeadersMiddleware
        from unittest.mock import AsyncMock
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_security_headers_lifespan_skipped(self):
        from app.core.security_headers_asgi import SecurityHeadersMiddleware
        from unittest.mock import AsyncMock
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()
        await middleware(scope, receive, send)
        app.assert_called_once()


class TestRetention:
    """app/core/retention.py coverage."""

    @pytest.mark.asyncio
    async def test_retention_policies(self):
        from app.core.retention import DEFAULT_RETENTION_POLICIES
        assert "metrics_retention_days" in DEFAULT_RETENTION_POLICIES
        assert "cleanup_enabled" in DEFAULT_RETENTION_POLICIES
        assert DEFAULT_RETENTION_POLICIES["cleanup_enabled"] is True

    @pytest.mark.asyncio
    async def test_validation_ranges(self):
        from app.core.retention import VALIDATION_RANGES
        assert "metrics_retention_days" in VALIDATION_RANGES
        min_val, max_val = VALIDATION_RANGES["metrics_retention_days"]
        assert min_val < max_val


class TestFilesystem:
    """app/core/filesystem.py coverage."""

    @pytest.mark.asyncio
    async def test_secure_path_valid(self, tmp_path):
        from app.core.filesystem import secure_path
        result = secure_path(str(tmp_path), "subdir/file.txt")
        assert result.is_relative_to(tmp_path)

    @pytest.mark.asyncio
    async def test_secure_path_traversal(self, tmp_path):
        from app.core.filesystem import secure_path
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            secure_path(str(tmp_path), "../../../etc/passwd")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_validate_avatar_filename_valid(self):
        from app.core.filesystem import validate_avatar_filename
        import uuid
        fname = f"{uuid.uuid4()}.png"
        validate_avatar_filename(fname)  # Should not raise

    @pytest.mark.asyncio
    async def test_validate_avatar_filename_invalid(self):
        from app.core.filesystem import validate_avatar_filename
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("../../../etc/passwd")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_validate_avatar_filename_invalid_ext(self):
        from app.core.filesystem import validate_avatar_filename
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("12345.exe")
        assert exc_info.value.status_code == 400


class TestSecurity:
    """app/core/security.py coverage."""

    @pytest.mark.asyncio
    async def test_get_user_permissions(self, test_user):
        from app.core.security import get_user_permissions
        perms = get_user_permissions(test_user)
        assert isinstance(perms, list)

    @pytest.mark.asyncio
    async def test_get_user_permissions_none_user(self):
        from app.core.security import get_user_permissions
        assert get_user_permissions(None) == []

    @pytest.mark.asyncio
    async def test_has_permission(self, test_user):
        from app.core.security import has_permission
        from app.core.permissions import Permission
        result = has_permission(test_user, Permission.SERVERS_READ_OWN)
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_has_permission_inactive(self, test_user):
        from app.core.security import has_permission
        from app.core.permissions import Permission
        test_user.is_active = False
        result = has_permission(test_user, Permission.SERVERS_READ_OWN)
        assert result is False

    @pytest.mark.asyncio
    async def test_has_any_permission(self, test_user):
        from app.core.security import has_any_permission
        from app.core.permissions import Permission
        result = has_any_permission(test_user, [Permission.SERVERS_READ_OWN])
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_has_all_permissions(self, test_user):
        from app.core.security import has_all_permissions
        from app.core.permissions import Permission
        result = has_all_permissions(test_user, [Permission.SERVERS_READ_OWN])
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_check_permission_raises(self, test_user):
        from app.core.security import check_permission
        from app.core.permissions import Permission
        from fastapi import HTTPException
        test_user.is_active = False
        with pytest.raises(HTTPException) as exc_info:
            check_permission(test_user, Permission.SERVERS_READ_OWN)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_check_any_permission_raises(self, test_user):
        from app.core.security import check_any_permission
        from app.core.permissions import Permission
        from fastapi import HTTPException
        test_user.is_active = False
        with pytest.raises(HTTPException) as exc_info:
            check_any_permission(test_user, [Permission.SERVERS_READ_OWN])
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_expand_permissions(self):
        from app.core.security import _expand_permissions
        from app.core.permissions import Permission
        result = _expand_permissions([Permission.SERVERS_WRITE_ALL])
        assert Permission.SERVERS_READ_OWN in result


class TestMain:
    """app/main.py coverage."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        from app.main import root
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        from app.main import health
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
