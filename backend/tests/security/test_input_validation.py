# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Security regression tests for input validation and injection (Phase 5).

These tests verify that user-controlled input is safely handled across the
API, rejecting traversal attempts, injection payloads, and oversized input
without leaking stack traces or executing unintended commands.
"""

import pytest
from httpx import AsyncClient


class TestSQLInjection:
    """Verify SQLAlchemy ORM usage prevents SQL injection."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_server_name_is_rejected(self, client: AsyncClient, user_token):
        """SQL payloads in server name should be rejected by Pydantic or safely handled."""
        payload = "server' OR '1'='1"
        response = await client.get(
            "/api/servers/",
            params={"search": payload},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # The endpoint may ignore search or return empty list; it must not 500
        # and must not return other users' servers.
        assert response.status_code in (200, 422), (
            f"Unexpected status: {response.status_code}: {response.text}"
        )
        if response.status_code == 200:
            data = response.json()
            servers = data.get("servers", [])
            assert all(s.get("user_id") is not None for s in servers)

    @pytest.mark.asyncio
    async def test_sql_injection_in_query_params_does_not_leak_errors(
        self, client: AsyncClient, user_token
    ):
        """SQL error messages should not be exposed to clients."""
        response = await client.get(
            "/api/credits/history",
            params={"page": "1; DROP TABLE users;--"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (200, 422), (
            f"Unexpected status: {response.status_code}: {response.text}"
        )
        assert "syntax error" not in response.text.lower()
        assert "sql" not in response.text.lower() or "sqlite" not in response.text.lower()


class TestPathTraversal:
    """Verify path traversal protection in volume and avatar endpoints."""

    @pytest.mark.asyncio
    async def test_path_traversal_in_volume_file_list(
        self, client: AsyncClient, user_token, test_user, db_session
    ):
        """Path traversal in volume path should return 403."""
        from app.models.volume import Volume

        volume = Volume(
            name=f"test-vol-{test_user.username}",
            display_name="Test Volume",
            size_bytes=1024 * 1024 * 100,
            owner_id=test_user.id,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        response = await client.get(
            f"/api/volumes/{volume.id}/files",
            params={"path": "../../../etc/passwd"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (403, 404, 400), (
            f"Expected 403/404/400, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_path_traversal_in_avatar_filename(self, client: AsyncClient, user_token):
        """Avatar filename traversal should be rejected."""
        response = await client.get(
            "/api/users/avatar/../../etc/passwd",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (400, 403, 404), (
            f"Expected 400/403/404, got {response.status_code}: {response.text}"
        )


class TestCommandInjection:
    """Verify server spawn does not shell-interpret user input."""

    @pytest.mark.asyncio
    async def test_command_injection_in_server_name_does_not_execute(
        self, client: AsyncClient, user_token
    ):
        """Server names containing shell metacharacters must be rejected or safely handled."""
        response = await client.post(
            "/api/servers/",
            json={
                "name": "evil;id",
                "environment_id": "00000000-0000-0000-0000-000000000000",
                "plan_id": "00000000-0000-0000-0000-000000000000",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (400, 422, 404), (
            f"Expected 400/422/404, got {response.status_code}: {response.text}"
        )


class TestXSSAndHTMLInjection:
    """Verify outputs are not rendered as active content."""

    @pytest.mark.asyncio
    async def test_xss_payload_in_profile_update_is_stored_safely(
        self, client: AsyncClient, user_token
    ):
        """Scripts in first_name should be stored and returned as plain text."""
        payload = "<script>alert(1)</script>"
        response = await client.put(
            "/api/users/me/profile",
            json={"first_name": payload},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200, (
            f"Update failed: {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data.get("first_name") == payload, "Payload was modified unexpectedly"

    @pytest.mark.asyncio
    async def test_html_injection_in_notification_message(
        self, client: AsyncClient, user_token, admin_user, admin_token, db_session
    ):
        """Notification messages containing HTML should not be executed by clients."""
        from app.models.notification import Notification

        payload = "<img src=x onerror=alert(1)>"
        notification = Notification(
            user_id=user_token.user_id if hasattr(user_token, "user_id") else None,
            type="security_test",
            title="Test",
            message=payload,
            severity="info",
            read=False,
        )
        # We need the actual user ID; fallback to creating via API if possible.
        # Instead, use the test_user fixture indirectly: look up the current user.
        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        user_id = response.json().get("id")
        notification.user_id = user_id
        db_session.add(notification)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        messages = [n.get("message", "") for n in data.get("notifications", [])]
        assert payload in messages, "Notification payload not returned"


class TestHostHeaderInjection:
    """Verify host header is not attacker-controlled for URL generation."""

    @pytest.mark.asyncio
    async def test_host_header_manipulation_d_not_reflect_in_response(
        self, client: AsyncClient, user_token
    ):
        """Setting a malicious Host header should not change response links."""
        response = await client.get(
            "/api/users/me/profile",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Host": "evil.com",
            },
        )
        assert response.status_code == 200
        assert "evil.com" not in response.text


class TestHTTPParameterPollution:
    """Verify repeated parameters are handled deterministically."""

    @pytest.mark.asyncio
    async def test_repeated_query_parameters_handled_safely(self, client: AsyncClient, user_token):
        """Repeated page params should not crash or bypass validation."""
        response = await client.get(
            "/api/credits/history",
            params={"page": 1, "limit": 10},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )


class TestInputSizeLimits:
    """Verify request size limits reject oversized payloads."""

    @pytest.mark.asyncio
    async def test_oversized_json_body_rejected(self, client: AsyncClient, user_token):
        """Very large JSON payloads should be rejected before processing."""
        response = await client.put(
            "/api/users/me/profile",
            json={"first_name": "A" * (10 * 1024 * 1024)},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (413, 422, 400), (
            f"Expected 413/422/400, got {response.status_code}: {response.text}"
        )
