"""Tests for cross-user server access restrictions.

Covers:
- JWT-only enforcement (API tokens blocked for cross-user access)
- Reason requirement for cross-user actions
- SERVERS_ACCESS_OTHERS permission enforcement
- Access-token endpoint reason requirement
"""

import pytest
import pytest_asyncio
import uuid
from datetime import datetime
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.server import Server


# ---------------------------------------------------------------------------
# Fixtures specific to cross-user tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def other_user_server(db_session, test_user):
    """Create a running server owned by test_user for cross-user access tests."""
    server = Server(
        id=uuid.uuid4(),
        name="other-user-server",
        user_id=test_user.id,
        status="running",
        container_id="container-other",
        external_url="http://localhost:8080",
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


@pytest_asyncio.fixture
async def admin_api_token(db_session, admin_user):
    """Create an API token for admin user with server management scopes."""
    from app.models.api_token import ApiToken
    from app.api.auth import get_password_hash
    import secrets

    raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
    token_hash = get_password_hash(raw_token)
    token_prefix = raw_token[:16]

    token = ApiToken(
        user_id=admin_user.id,
        name="Admin API Token",
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=["servers:read", "servers:start", "servers:stop", "servers:delete", "servers:manage"],
        is_active=True,
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)

    from types import SimpleNamespace
    return SimpleNamespace(db_token=token, raw_token=raw_token)


# ---------------------------------------------------------------------------
# JWT-only enforcement for cross-user access
# ---------------------------------------------------------------------------

class TestCrossUserJwtOnly:
    """Cross-user server access must use JWT, not API tokens."""

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_viewing_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from GET /servers/{id} on another user's server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_starting_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from POST /servers/{id}/start on another user's server."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/start",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_stopping_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from POST /servers/{id}/stop on another user's server."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/stop",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_restarting_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from POST /servers/{id}/restart on another user's server."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/restart",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_deleting_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from DELETE /servers/{id} on another user's server."""
        response = await client.delete(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_access_token_on_other_user_server(self, client: AsyncClient, admin_api_token, other_user_server):
        """Admin API token should be blocked from POST /servers/{id}/access-token on another user's server."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/access-token",
            headers={"Authorization": f"Bearer {admin_api_token.raw_token}"},
            json={},
        )
        assert response.status_code == 403
        assert "requires jwt authentication" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_api_token_can_access_own_server(self, client: AsyncClient, api_token, other_user_server):
        """API token should still work for GET on the token owner's own server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(other_user_server.id)

    @pytest.mark.asyncio
    async def test_jwt_admin_can_view_other_user_server(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT should be allowed to view another user's server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(other_user_server.id)


# ---------------------------------------------------------------------------
# Reason requirement for cross-user actions
# ---------------------------------------------------------------------------

class TestCrossUserReasonRequired:
    """Cross-user server actions require a reason."""

    @pytest.mark.asyncio
    async def test_start_other_user_server_without_reason_fails(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT starting another user's server without reason should 400."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/start",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
        assert "reason is required" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_stop_other_user_server_without_reason_fails(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT stopping another user's server without reason should 400."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/stop",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
        assert "reason is required" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_restart_other_user_server_without_reason_fails(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT restarting another user's server without reason should 400."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/restart",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
        assert "reason is required" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_other_user_server_without_reason_fails(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT deleting another user's server without reason should 400."""
        response = await client.delete(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
        assert "reason is required" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_access_token_without_reason_fails(self, client: AsyncClient, admin_token, other_user_server):
        """Admin JWT requesting access-token for another user's server without reason should 400."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/access-token",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        assert response.status_code == 400
        assert "reason is required" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_own_server_without_reason_succeeds(self, client: AsyncClient, user_token, test_user, db_session):
        """User starting their OWN server should NOT require a reason."""
        server = Server(
            id=uuid.uuid4(),
            name="own-server-start",
            user_id=test_user.id,
            status="stopped",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()

        with patch("app.api.servers.spawner.start", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = True
            response = await client.post(
                f"/api/servers/{server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        # Should NOT be blocked by reason check (may fail on other things, but not 400 for reason)
        assert response.status_code != 400 or "reason" not in response.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_stop_own_server_without_reason_succeeds(self, client: AsyncClient, user_token, test_user, db_session):
        """User stopping their OWN server should NOT require a reason."""
        server = Server(
            id=uuid.uuid4(),
            name="own-server-stop",
            user_id=test_user.id,
            status="running",
            container_id="container-own",
        )
        db_session.add(server)
        await db_session.commit()

        with patch("app.api.servers.spawner.stop", new_callable=AsyncMock) as mock_stop:
            mock_stop.return_value = True
            response = await client.post(
                f"/api/servers/{server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code != 400 or "reason" not in response.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# SERVERS_ACCESS_OTHERS permission enforcement
# ---------------------------------------------------------------------------

class TestServersAccessOthersPermission:
    """Support and user roles lack SERVERS_ACCESS_OTHERS and should be blocked."""

    @pytest.mark.asyncio
    async def test_support_user_blocked_from_other_user_server(self, client: AsyncClient, support_token, other_user_server):
        """Support user JWT should be blocked from viewing another user's server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {support_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_support_user_blocked_from_starting_other_user_server(self, client: AsyncClient, support_token, other_user_server):
        """Support user JWT should be blocked from starting another user's server."""
        response = await client.post(
            f"/api/servers/{other_user_server.id}/start",
            headers={"Authorization": f"Bearer {support_token}"},
            json={"reason": "Testing"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_moderator_can_view_other_user_server(self, client: AsyncClient, moderator_token, other_user_server):
        """Moderator JWT should be allowed to view another user's server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {moderator_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_superadmin_can_view_other_user_server(self, client: AsyncClient, superadmin_token, other_user_server):
        """Super admin JWT should be allowed to view another user's server."""
        response = await client.get(
            f"/api/servers/{other_user_server.id}",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Audit logging for cross-user access
# ---------------------------------------------------------------------------

class TestCrossUserAuditLogging:
    """Cross-user actions should create activity logs and notifications."""

    @pytest.mark.asyncio
    async def test_stop_other_user_server_creates_audit_log(self, client: AsyncClient, admin_token, other_user_server, db_session):
        """Stopping another user's server with reason should log an audit entry."""
        from sqlalchemy import select
        from app.models.activity_log import ActivityLog

        with patch("app.api.servers.spawner.stop", new_callable=AsyncMock) as mock_stop:
            mock_stop.return_value = True
            response = await client.post(
                f"/api/servers/{other_user_server.id}/stop",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"reason": "Maintenance window"},
            )

        assert response.status_code in [200, 202]

        # Check activity log was created
        result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.target_type == "server",
                ActivityLog.target_id == str(other_user_server.id),
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert "Maintenance window" in str(log.details)

    @pytest.mark.asyncio
    async def test_cross_user_access_token_creates_audit_log(self, client: AsyncClient, admin_token, other_user_server, db_session):
        """Access-token request for another user's server should log an audit entry."""
        from sqlalchemy import select
        from app.models.activity_log import ActivityLog

        with patch("app.services.server_auth_service.server_auth_service.generate_access_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "test-access-token"
            response = await client.post(
                f"/api/servers/{other_user_server.id}/access-token",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"reason": "Troubleshooting"},
            )
        assert response.status_code == 200

        result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.target_type == "server",
                ActivityLog.target_id == str(other_user_server.id),
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert "Troubleshooting" in str(log.details)
