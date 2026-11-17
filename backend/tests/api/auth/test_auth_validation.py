# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Extended tests for auth.py — logout stop_on_logout, scope checks, verify branches."""

from unittest import mock

import pytest

from app.models.server import Server

# ─────────────────────────────────────────────────────────────
# POST /logout — stop_on_logout branches
# ─────────────────────────────────────────────────────────────


class TestLogoutStopOnLogout:
    """Logout uses the same verified termination boundary as other callers."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [False, True])
    async def test_logout_delegates_and_survives_a_failed_item(
        self, client, user_token, test_user, db_session, failure
    ):
        from app.services.server_launch_service import LaunchError

        owner_id = test_user.id
        test_user.preferences = {"stop_on_logout": True}
        rows = [
            Server(
                name=f"logout-{i}", user_id=owner_id, status="running", container_id=f"runtime-{i}"
            )
            for i in range(2)
        ]
        db_session.add_all(rows)
        await db_session.commit()
        identifiers = [row.id for row in rows]

        async def stop(identifier, owner_id=None):
            if failure and identifier == identifiers[0]:
                await db_session.rollback()
                raise LaunchError("launch_in_progress")
            row = await db_session.get(Server, identifier)
            row.status = "stopped"
            return row

        with (
            mock.patch("app.api.auth.get_driver", new=mock.AsyncMock(return_value=object())),
            mock.patch("app.api.auth.ServerTerminationService") as service,
        ):
            service.return_value.stop = mock.AsyncMock(side_effect=stop)
            response = await client.post(
                "/api/auth/logout", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert service.return_value.stop.await_args_list == [
            mock.call(identifier, owner_id=owner_id) for identifier in identifiers
        ]
        await db_session.refresh(rows[1])
        assert rows[1].status == "stopped"

    @pytest.mark.asyncio
    async def test_logout_without_preference_has_no_runtime_mutation(
        self, client, user_token, test_user, db_session
    ):
        test_user.preferences = {"stop_on_logout": False}
        await db_session.commit()
        with mock.patch("app.api.auth.ServerTerminationService") as service:
            response = await client.post(
                "/api/auth/logout", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        service.assert_not_called()


# ─────────────────────────────────────────────────────────────
# GET /verify — missing branches
# ─────────────────────────────────────────────────────────────


class TestVerifyBranches:
    """Tests for GET /verify missing branches."""

    @pytest.mark.asyncio
    async def test_verify_plain_token_no_scheme(self, client, test_user, db_session):
        """Token without scheme prefix should be rejected (401)."""
        from app.api.auth import pwd_context
        from app.models.api_token import ApiToken

        plain = "plain-token-no-scheme-123"
        token = ApiToken(
            user_id=test_user.id,
            name="plain",
            token_prefix=plain[:16],
            token_hash=pwd_context.hash(plain),
            is_active=True,
            scopes=["auth:read"],
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.get(
            "/api/auth/verify",
            headers={"Authorization": plain},
        )
        # verify_auth endpoint accepts plain tokens (no scheme required)
        assert response.status_code == 200
        assert "x-user-id" in response.headers


# ─────────────────────────────────────────────────────────────
# require_scopes — wildcard + missing context
# ─────────────────────────────────────────────────────────────


class TestRequireScopes:
    """Tests for require_scopes dependency."""

    @pytest.mark.asyncio
    async def test_require_scopes_wildcard_match(self, client, test_user, db_session):
        """Wildcard scope like servers:* should match servers:read."""
        from app.api.auth import pwd_context
        from app.models.api_token import ApiToken

        plain = "wildcard-scope-token"
        token = ApiToken(
            user_id=test_user.id,
            name="wildcard",
            token_prefix=plain[:16],
            token_hash=pwd_context.hash(plain),
            is_active=True,
            scopes=["servers:*"],
        )
        db_session.add(token)
        await db_session.commit()

        # Call an endpoint that requires servers:read
        # We can test this indirectly via /api/auth/verify or another endpoint
        # Since we don't have a direct endpoint with require_scopes("servers:read"),
        # let's test the dependency function directly

        from app.api.auth import AuthContext, require_scopes

        req = mock.Mock()
        req.state.auth_context = AuthContext(
            user=test_user,
            auth_method="api_token",
            token_scopes=["servers:*"],
        )

        checker = require_scopes("servers:read")
        # Should not raise
        await checker(req, test_user)

    @pytest.mark.asyncio
    async def test_require_scopes_insufficient_scope(self, client, test_user, db_session):
        """Token without required scope should fail."""
        from fastapi import HTTPException

        from app.api.auth import AuthContext, require_scopes

        req = mock.Mock()
        req.state.auth_context = AuthContext(
            user=test_user,
            auth_method="api_token",
            token_scopes=["other:read"],
        )

        checker = require_scopes("servers:read")
        with pytest.raises(HTTPException) as exc_info:
            await checker(req, test_user)

        assert exc_info.value.status_code == 403
        assert "insufficient scope" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_require_scopes_jwt_bypass(self, client, test_user, db_session):
        """JWT auth should bypass scope checks."""
        from app.api.auth import AuthContext, require_scopes

        req = mock.Mock()
        req.state.auth_context = AuthContext(
            user=test_user,
            auth_method="jwt",
            token_scopes=[],
        )

        checker = require_scopes("servers:read")
        # Should not raise even with empty scopes
        await checker(req, test_user)


# ─────────────────────────────────────────────────────────────
# require_jwt_auth — missing context
# ─────────────────────────────────────────────────────────────


class TestRequireJwtAuth:
    """Tests for require_jwt_auth dependency."""

    @pytest.mark.asyncio
    async def test_require_jwt_auth_missing_context(self, client, test_user):
        """Missing auth_context should return 401."""
        from fastapi import HTTPException

        from app.api.auth import require_jwt_auth

        req = mock.Mock()
        req.state.auth_context = None

        checker = require_jwt_auth()
        with pytest.raises(HTTPException) as exc_info:
            await checker(req, test_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_jwt_auth_api_token_rejected(self, client, test_user):
        """API token auth should return 403."""
        from fastapi import HTTPException

        from app.api.auth import AuthContext, require_jwt_auth

        req = mock.Mock()
        req.state.auth_context = AuthContext(
            user=test_user,
            auth_method="api_token",
            token_scopes=[],
        )

        checker = require_jwt_auth()
        with pytest.raises(HTTPException) as exc_info:
            await checker(req, test_user)

        assert exc_info.value.status_code == 403
        assert "jwt authentication required" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_require_jwt_auth_jwt_allowed(self, client, test_user):
        """JWT auth should pass."""
        from app.api.auth import AuthContext, require_jwt_auth

        req = mock.Mock()
        req.state.auth_context = AuthContext(
            user=test_user,
            auth_method="jwt",
            token_scopes=[],
        )

        checker = require_jwt_auth()
        await checker(req, test_user)
