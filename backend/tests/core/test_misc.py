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
        from app.core.roles import _expand_permissions
        from app.core.permissions import Permission

        result = _expand_permissions([Permission.SERVERS_WRITE_ALL])
        assert Permission.SERVERS_READ_OWN in result
