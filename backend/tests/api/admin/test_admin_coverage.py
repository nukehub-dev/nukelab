# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage-focused unit tests for uncovered branches in app.api.admin.

These tests call the endpoint functions directly with mocked dependencies
(AsyncMock DB sessions, patched services) so error paths and edge branches
can be exercised deterministically without external services.
"""

import uuid
from datetime import UTC, datetime
from unittest import mock

import pytest
from fastapi import HTTPException

from app.api.admin import (
    BulkActionRequest,
    BulkCreditGrantRequest,
    BulkServerActionRequest,
    BulkSetAllowanceRequest,
    DefaultQuotaLimitsRequest,
    EmailTestRequest,
    UpdateSystemAllowanceWindowRequest,
    UpdateSystemDailyAllowanceRequest,
    UpdateSystemInitialBalanceRequest,
    UpdateSystemMaxBalanceRequest,
    admin_refresh_volume_sizes,
    admin_revoke_user_tokens,
    bulk_grant_credits,
    bulk_server_action,
    bulk_set_daily_allowance,
    bulk_user_action,
    export_activity_logs,
    get_activity_logs,
    get_default_quota_limits,
    get_email_status,
    get_health_monitoring,
    get_system_allowance_login_window,
    get_system_daily_allowance,
    get_system_initial_balance,
    get_system_max_balance,
    update_default_quota_limits,
    update_system_allowance_login_window,
    update_system_daily_allowance,
    update_system_initial_balance,
    update_system_max_balance,
)
from app.api.admin import (
    test_email as send_test_email,
)


def _unwrap(fn):
    """Return the undecorated endpoint (endpoints may be wrapped by slowapi)."""
    return getattr(fn, "__wrapped__", fn)


def _result(*, scalar=None, scalars=None, all_rows=None):
    """Build a mock DB result object."""
    res = mock.Mock()
    res.scalar.return_value = scalar
    res.scalars.return_value.all.return_value = scalars if scalars is not None else []
    res.all.return_value = all_rows if all_rows is not None else []
    return res


def _db(results):
    """Build an AsyncMock DB session whose execute() yields the given results."""
    db = mock.AsyncMock()
    db.execute = mock.AsyncMock(side_effect=list(results))
    return db


def _admin_user():
    return mock.Mock(id=uuid.uuid4(), username="admin", email="admin@example.com")


class _BrokenSecurityUser:
    """User-like object whose ``security`` property raises (exercise error path)."""

    def __init__(self, uid):
        self.id = uid
        self.is_active = True

    @property
    def security(self):
        raise RuntimeError("security column unreadable")


# ----------------------------------------------------------------------
# Bulk user action
# ----------------------------------------------------------------------


class TestBulkUserAction:
    @pytest.mark.asyncio
    async def test_invalid_user_id_format(self):
        body = BulkActionRequest(action="disable", user_ids=["not-a-uuid"])
        with pytest.raises(HTTPException) as exc_info:
            await _unwrap(bulk_user_action)(
                mock.Mock(), body, current_user=_admin_user(), db=_db([])
            )
        assert exc_info.value.status_code == 400
        assert "Invalid user ID format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        body = BulkActionRequest(action="explode", user_ids=[str(uuid.uuid4())])
        db = _db([_result(scalars=[])])
        with pytest.raises(HTTPException) as exc_info:
            await _unwrap(bulk_user_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )
        assert exc_info.value.status_code == 400
        assert "Unknown action" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_users_removes_avatar_files(self):
        u1 = mock.Mock(id=uuid.uuid4())
        u2 = mock.Mock(id=uuid.uuid4())
        missing_id = str(uuid.uuid4())
        body = BulkActionRequest(
            action="delete", user_ids=[str(u1.id), str(u2.id), missing_id]
        )
        db = _db([_result(scalars=[u1, u2])])

        avatar_file = f"{u1.id}_avatar.png"
        with (
            mock.patch("os.path.isdir", return_value=True),
            mock.patch("os.listdir", return_value=[avatar_file, "unrelated.txt"]),
            mock.patch("os.remove") as mock_remove,
        ):
            response = await _unwrap(bulk_user_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        assert db.delete.await_count == 2
        db.commit.assert_awaited_once()
        mock_remove.assert_called_once()
        assert avatar_file in mock_remove.call_args.args[0]
        assert set(response["results"]["success"]) == {str(u1.id), str(u2.id)}
        assert response["results"]["failed"] == [
            {"user_id": missing_id, "error": "User not found"}
        ]

    @pytest.mark.asyncio
    async def test_delete_avatar_cleanup_errors_are_swallowed(self):
        u1 = mock.Mock(id=uuid.uuid4())
        body = BulkActionRequest(action="delete", user_ids=[str(u1.id)])
        db = _db([_result(scalars=[u1])])

        with (
            mock.patch("os.path.isdir", return_value=True),
            mock.patch("os.listdir", side_effect=OSError("disk gone")),
        ):
            response = await _unwrap(bulk_user_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )
        assert response["results"]["success"] == [str(u1.id)]

    @pytest.mark.asyncio
    async def test_delete_per_user_exception_is_recorded(self):
        u1 = mock.Mock(id=uuid.uuid4())
        body = BulkActionRequest(action="delete", user_ids=[str(u1.id)])
        db = _db([_result(scalars=[u1])])
        db.delete.side_effect = RuntimeError("constraint violation")

        with mock.patch("os.path.isdir", return_value=False):
            response = await _unwrap(bulk_user_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        assert response["results"]["success"] == []
        assert response["results"]["failed"] == [
            {"user_id": str(u1.id), "error": "constraint violation"}
        ]
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disable_sets_security_fields(self):
        u1 = mock.Mock(id=uuid.uuid4(), is_active=True, security={})
        body = BulkActionRequest(action="disable", user_ids=[str(u1.id)])
        db = _db([_result(scalars=[u1])])

        response = await _unwrap(bulk_user_action)(
            mock.Mock(), body, current_user=_admin_user(), db=db
        )

        assert response["results"]["success"] == [str(u1.id)]
        assert u1.is_active is False
        assert "disabled_at" in u1.security
        assert u1.security["disabled_reason"] is None

    @pytest.mark.asyncio
    async def test_enable_clears_security_fields(self):
        u1 = mock.Mock(
            id=uuid.uuid4(),
            is_active=False,
            security={"disabled_reason": "spam", "disabled_at": "2024-01-01"},
        )
        body = BulkActionRequest(action="enable", user_ids=[str(u1.id)])
        db = _db([_result(scalars=[u1])])

        response = await _unwrap(bulk_user_action)(
            mock.Mock(), body, current_user=_admin_user(), db=db
        )

        assert response["results"]["success"] == [str(u1.id)]
        assert u1.is_active is True
        assert "disabled_reason" not in u1.security
        assert "disabled_at" not in u1.security

    @pytest.mark.asyncio
    async def test_disable_per_user_exception_is_recorded(self):
        uid = uuid.uuid4()
        broken = _BrokenSecurityUser(uid)
        body = BulkActionRequest(action="disable", user_ids=[str(uid)])
        db = _db([_result(scalars=[broken])])

        response = await _unwrap(bulk_user_action)(
            mock.Mock(), body, current_user=_admin_user(), db=db
        )

        assert response["results"]["success"] == []
        assert response["results"]["failed"] == [
            {"user_id": str(uid), "error": "security column unreadable"}
        ]
        db.commit.assert_awaited_once()


# ----------------------------------------------------------------------
# Revoke user tokens
# ----------------------------------------------------------------------


class TestRevokeUserTokens:
    @pytest.mark.asyncio
    async def test_user_not_found(self):
        service = mock.AsyncMock()
        service.get_by_username.return_value = None
        with mock.patch("app.api.admin.UserService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await admin_revoke_user_tokens(
                    "ghost", current_user=_admin_user(), db=mock.AsyncMock()
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_success(self):
        user = mock.Mock(username="victim")
        service = mock.AsyncMock()
        service.get_by_username.return_value = user
        with (
            mock.patch("app.api.admin.UserService", return_value=service),
            mock.patch("app.api.admin.token_revocation_service") as mock_revoker,
        ):
            mock_revoker.revoke_user_tokens = mock.AsyncMock()
            response = await admin_revoke_user_tokens(
                "victim", current_user=_admin_user(), db=mock.AsyncMock()
            )

        mock_revoker.revoke_user_tokens.assert_awaited_once_with(sub="victim")
        assert response["username"] == "victim"
        assert "revoked_at" in response
        assert "victim" in response["message"]


# ----------------------------------------------------------------------
# Bulk server action
# ----------------------------------------------------------------------


def _server(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "container_id": "cid-123",
        "name": "srv",
        "status": "stopped",
        "image": "img:latest",
        "volume_id": None,
        "external_url": None,
    }
    defaults.update(overrides)
    return mock.Mock(**defaults)


class TestBulkServerAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        body = BulkServerActionRequest(action="explode", server_ids=[])
        with pytest.raises(HTTPException) as exc_info:
            await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=_db([])
            )
        assert exc_info.value.status_code == 400
        assert "Unknown action" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_server_id_format(self):
        body = BulkServerActionRequest(action="stop", server_ids=["not-a-uuid"])
        with pytest.raises(HTTPException) as exc_info:
            await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=_db([])
            )
        assert exc_info.value.status_code == 400
        assert "Invalid server ID format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_stop_releases_gpu_even_when_release_fails(self):
        server = _server()
        sid = str(server.id)
        body = BulkServerActionRequest(action="stop", server_ids=[sid])
        db = _db([_result(scalars=[server])])

        allocator = mock.AsyncMock()
        allocator.release.side_effect = RuntimeError("gpu release boom")
        with (
            mock.patch("app.container.spawner.spawner") as mock_spawner,
            mock.patch(
                "app.services.gpu_allocator.GpuAllocatorService", return_value=allocator
            ),
            mock.patch(
                "app.api.servers._invalidate_server_list_cache", new=mock.AsyncMock()
            ) as mock_invalidate,
            mock.patch("app.api.admin.broadcast_server_status_change") as mock_broadcast,
        ):
            mock_spawner.stop = mock.AsyncMock()
            response = await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        mock_spawner.stop.assert_awaited_once_with("cid-123")
        assert server.status == "stopped"
        assert response["results"]["success"] == [sid]
        allocator.release.assert_awaited_once_with(sid)
        mock_broadcast.assert_awaited_once_with(str(server.user_id), sid, "stopped")
        mock_invalidate.assert_awaited_once_with(str(server.user_id))

    @pytest.mark.asyncio
    async def test_start_gpu_server_respawns_container(self):
        server = _server()
        sid = str(server.id)
        body = BulkServerActionRequest(action="start", server_ids=[sid])
        db = _db([_result(scalars=[server])])

        new_server = mock.Mock(
            container_id="cid-new",
            image="img:v2",
            volume_id=uuid.uuid4(),
            external_url="https://srv.example.com",
        )
        with (
            mock.patch("app.container.spawner.spawner") as mock_spawner,
            mock.patch(
                "app.api.servers._gpu_requires_recreate",
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch(
                "app.api.servers._respawn_server_container",
                new=mock.AsyncMock(return_value=new_server),
            ) as mock_respawn,
            mock.patch(
                "app.services.gpu_allocator.GpuAllocatorService",
                return_value=mock.AsyncMock(),
            ),
            mock.patch(
                "app.api.servers._invalidate_server_list_cache", new=mock.AsyncMock()
            ),
            mock.patch("app.api.admin.broadcast_server_status_change"),
        ):
            mock_spawner.start = mock.AsyncMock()
            response = await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        mock_respawn.assert_awaited_once()
        mock_spawner.start.assert_not_awaited()
        assert server.container_id == "cid-new"
        assert server.image == "img:v2"
        assert server.volume_id == new_server.volume_id
        assert server.external_url == "https://srv.example.com"
        assert server.status == "running"
        assert response["results"]["success"] == [sid]

    @pytest.mark.asyncio
    async def test_start_plain_container_uses_spawner(self):
        server = _server()
        sid = str(server.id)
        body = BulkServerActionRequest(action="start", server_ids=[sid])
        db = _db([_result(scalars=[server])])

        with (
            mock.patch("app.container.spawner.spawner") as mock_spawner,
            mock.patch(
                "app.api.servers._gpu_requires_recreate",
                new=mock.AsyncMock(return_value=False),
            ),
            mock.patch(
                "app.services.gpu_allocator.GpuAllocatorService",
                return_value=mock.AsyncMock(),
            ),
            mock.patch(
                "app.api.servers._invalidate_server_list_cache", new=mock.AsyncMock()
            ),
            mock.patch("app.api.admin.broadcast_server_status_change"),
        ):
            mock_spawner.start = mock.AsyncMock()
            response = await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        mock_spawner.start.assert_awaited_once_with("cid-123")
        assert server.status == "running"
        assert response["results"]["success"] == [sid]

    @pytest.mark.asyncio
    async def test_per_server_exception_and_missing_ids(self):
        server = _server()
        sid = str(server.id)
        missing_sid = str(uuid.uuid4())
        body = BulkServerActionRequest(action="stop", server_ids=[sid, missing_sid])
        db = _db([_result(scalars=[server])])

        with (
            mock.patch("app.container.spawner.spawner") as mock_spawner,
            mock.patch(
                "app.services.gpu_allocator.GpuAllocatorService",
                return_value=mock.AsyncMock(),
            ),
            mock.patch(
                "app.api.servers._invalidate_server_list_cache", new=mock.AsyncMock()
            ),
            mock.patch("app.api.admin.broadcast_server_status_change"),
        ):
            mock_spawner.stop = mock.AsyncMock(side_effect=RuntimeError("docker down"))
            response = await _unwrap(bulk_server_action)(
                mock.Mock(), body, current_user=_admin_user(), db=db
            )

        assert response["results"]["success"] == []
        failed = {f["server_id"]: f["error"] for f in response["results"]["failed"]}
        assert failed[sid] == "docker down"
        assert failed[missing_sid] == "Server not found"
        db.commit.assert_awaited_once()


# ----------------------------------------------------------------------
# System credit settings (get/put pairs)
# ----------------------------------------------------------------------


def _setting_service(**methods):
    service = mock.AsyncMock()
    for name, value in methods.items():
        getattr(service, name).return_value = value
    return service


class TestCreditSystemSettings:
    @pytest.mark.asyncio
    async def test_get_default_allowance(self):
        service = _setting_service(get_daily_allowance=250)
        with mock.patch(
            "app.services.setting_service.SettingService", return_value=service
        ):
            response = await get_system_daily_allowance(
                current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert response == {"default_daily_allowance": 250}

    @pytest.mark.asyncio
    async def test_update_default_allowance(self):
        service = _setting_service()
        activity = mock.AsyncMock()
        admin = _admin_user()
        with (
            mock.patch("app.services.setting_service.SettingService", return_value=service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await update_system_daily_allowance(
                UpdateSystemDailyAllowanceRequest(amount=300),
                current_user=admin,
                db=mock.AsyncMock(),
            )
        service.set_daily_allowance.assert_awaited_once_with(300)
        activity.log.assert_awaited_once()
        assert activity.log.call_args.kwargs["actor_id"] == str(admin.id)
        assert activity.log.call_args.kwargs["details"] == {"amount": 300}
        assert "300" in response["message"]

    @pytest.mark.asyncio
    async def test_get_max_balance(self):
        service = _setting_service(get_max_balance=10000)
        with mock.patch(
            "app.services.setting_service.SettingService", return_value=service
        ):
            response = await get_system_max_balance(
                current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert response == {"max_balance": 10000}

    @pytest.mark.asyncio
    async def test_update_max_balance(self):
        service = _setting_service()
        activity = mock.AsyncMock()
        with (
            mock.patch("app.services.setting_service.SettingService", return_value=service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await update_system_max_balance(
                UpdateSystemMaxBalanceRequest(amount=5000),
                current_user=_admin_user(),
                db=mock.AsyncMock(),
            )
        service.set_max_balance.assert_awaited_once_with(5000)
        assert "5000" in response["message"]

    @pytest.mark.asyncio
    async def test_get_initial_balance(self):
        service = _setting_service(get_initial_balance=100)
        with mock.patch(
            "app.services.setting_service.SettingService", return_value=service
        ):
            response = await get_system_initial_balance(
                current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert response == {"initial_balance": 100}

    @pytest.mark.asyncio
    async def test_update_initial_balance(self):
        service = _setting_service()
        activity = mock.AsyncMock()
        with (
            mock.patch("app.services.setting_service.SettingService", return_value=service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await update_system_initial_balance(
                UpdateSystemInitialBalanceRequest(amount=50),
                current_user=_admin_user(),
                db=mock.AsyncMock(),
            )
        service.set_initial_balance.assert_awaited_once_with(50)
        assert "50" in response["message"]

    @pytest.mark.asyncio
    async def test_get_allowance_login_window(self):
        service = _setting_service(get_daily_allowance_login_window_hours=48)
        with mock.patch(
            "app.services.setting_service.SettingService", return_value=service
        ):
            response = await get_system_allowance_login_window(
                current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert response == {"login_window_hours": 48}

    @pytest.mark.asyncio
    async def test_update_allowance_login_window(self):
        service = _setting_service()
        activity = mock.AsyncMock()
        with (
            mock.patch("app.services.setting_service.SettingService", return_value=service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await update_system_allowance_login_window(
                UpdateSystemAllowanceWindowRequest(hours=72),
                current_user=_admin_user(),
                db=mock.AsyncMock(),
            )
        service.set_daily_allowance_login_window_hours.assert_awaited_once_with(72)
        assert "72" in response["message"]


# ----------------------------------------------------------------------
# Default quota limits
# ----------------------------------------------------------------------


class TestDefaultQuotaLimits:
    @pytest.mark.asyncio
    async def test_get_default_quota_limits(self):
        limits = {"max_cpu_total": 4, "max_memory_total": "16g"}
        service = _setting_service(get_quota_defaults=limits)
        with mock.patch(
            "app.services.setting_service.SettingService", return_value=service
        ):
            response = await get_default_quota_limits(
                current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert response == {"default_limits": limits}

    @pytest.mark.asyncio
    async def test_update_default_quota_limits(self):
        new_limits = {
            "max_cpu_total": 8,
            "max_memory_total": "32g",
            "max_disk_total": "200g",
            "max_gpu_total": 2,
            "max_servers_total": 10,
        }
        service = _setting_service(get_quota_defaults=new_limits)
        activity = mock.AsyncMock()
        with (
            mock.patch("app.services.setting_service.SettingService", return_value=service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await update_default_quota_limits(
                DefaultQuotaLimitsRequest(**new_limits),
                current_user=_admin_user(),
                db=mock.AsyncMock(),
            )
        service.set_quota_defaults.assert_awaited_once_with(new_limits)
        activity.log.assert_awaited_once()
        assert response["default_limits"] == new_limits
        assert "updated" in response["message"]


# ----------------------------------------------------------------------
# Bulk daily allowance
# ----------------------------------------------------------------------


class TestBulkSetAllowance:
    @pytest.mark.asyncio
    async def test_empty_user_ids(self):
        body = BulkSetAllowanceRequest.model_construct(user_ids=[], amount=10)
        with pytest.raises(HTTPException) as exc_info:
            await bulk_set_daily_allowance(
                body, current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert exc_info.value.status_code == 400
        assert "No user IDs" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_user_id_format(self):
        body = BulkSetAllowanceRequest(user_ids=["bad-uuid"], amount=10)
        with pytest.raises(HTTPException) as exc_info:
            await bulk_set_daily_allowance(
                body, current_user=_admin_user(), db=mock.AsyncMock()
            )
        assert exc_info.value.status_code == 400
        assert "Invalid user ID format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_mixed_success_missing_and_failures(self):
        good = mock.Mock(id=uuid.uuid4())
        http_fail = mock.Mock(id=uuid.uuid4())
        boom_fail = mock.Mock(id=uuid.uuid4())
        missing_id = str(uuid.uuid4())
        body = BulkSetAllowanceRequest(
            user_ids=[str(good.id), str(http_fail.id), str(boom_fail.id), missing_id],
            amount=120,
        )
        db = _db([_result(scalars=[good, http_fail, boom_fail])])

        user_service = mock.AsyncMock()

        async def _update_user(*, user_id, data, updated_by):
            if user_id == str(good.id):
                return mock.Mock(daily_allowance=120)
            if user_id == str(http_fail.id):
                raise HTTPException(status_code=404, detail="User not found")
            raise RuntimeError("db exploded")

        user_service.update_user.side_effect = _update_user
        activity = mock.AsyncMock()

        with (
            mock.patch("app.services.user_service.UserService", return_value=user_service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await bulk_set_daily_allowance(
                body, current_user=_admin_user(), db=db
            )

        results = response["results"]
        assert results["success"] == [
            {"user_id": str(good.id), "daily_allowance": 120}
        ]
        failed = {f["user_id"]: f["error"] for f in results["failed"]}
        assert failed[str(http_fail.id)] == "User not found"
        assert failed[str(boom_fail.id)] == "db exploded"
        assert failed[missing_id] == "User not found"
        assert "1/4" in response["message"]
        activity.log.assert_awaited_once()
        assert activity.log.call_args.kwargs["details"]["bulk"] is True


# ----------------------------------------------------------------------
# Bulk credit grant
# ----------------------------------------------------------------------


class TestBulkGrantCredits:
    @pytest.mark.asyncio
    async def test_success_and_cap_flag(self):
        tx = mock.Mock(id=uuid.uuid4(), amount=40, balance_after=240)
        credit_service = mock.AsyncMock()
        credit_service.grant_credits.return_value = tx
        activity = mock.AsyncMock()
        admin = _admin_user()
        uid = str(uuid.uuid4())

        with (
            mock.patch("app.api.admin.CreditService", return_value=credit_service),
            mock.patch(
                "app.services.activity_service.ActivityService", return_value=activity
            ),
        ):
            response = await bulk_grant_credits(
                BulkCreditGrantRequest(user_ids=[uid], amount=100, reason="promo"),
                current_user=admin,
                db=mock.AsyncMock(),
            )

        credit_service.grant_credits.assert_awaited_once_with(
            user_id=uid, amount=100, actor_id=str(admin.id), reason="promo"
        )
        entry = response["results"]["success"][0]
        assert entry == {
            "user_id": uid,
            "granted_amount": 40,
            "new_balance": 240,
            "capped": True,
        }
        activity.log.assert_awaited_once()
        details = activity.log.call_args.kwargs["details"]
        assert details["transaction_id"] == str(tx.id)
        assert details["granted_amount"] == 40

    @pytest.mark.asyncio
    async def test_per_user_failure_is_recorded(self):
        credit_service = mock.AsyncMock()
        credit_service.grant_credits.side_effect = RuntimeError("ledger locked")
        uid = str(uuid.uuid4())

        with (
            mock.patch("app.api.admin.CreditService", return_value=credit_service),
            mock.patch(
                "app.services.activity_service.ActivityService",
                return_value=mock.AsyncMock(),
            ),
        ):
            response = await bulk_grant_credits(
                BulkCreditGrantRequest(user_ids=[uid], amount=10, reason="x"),
                current_user=_admin_user(),
                db=mock.AsyncMock(),
            )

        assert response["results"]["success"] == []
        assert response["results"]["failed"] == [{"user_id": uid, "error": "ledger locked"}]


# ----------------------------------------------------------------------
# Activity log filters / export
# ----------------------------------------------------------------------


class TestActivityFilters:
    @pytest.mark.asyncio
    async def test_list_with_user_id_filter(self):
        log = mock.Mock()
        log.to_dict.return_value = {"id": "1"}
        db = _db([_result(scalar=1), _result(scalars=[log])])

        response = await get_activity_logs(
            user_id=str(uuid.uuid4()),
            action="server.create",
            target_type="server",
            from_date=datetime(2024, 1, 1, tzinfo=UTC),
            to_date=datetime(2024, 12, 31, tzinfo=UTC),
            page=2,
            limit=10,
            current_user=_admin_user(),
            db=db,
        )

        assert response["logs"] == [{"id": "1"}]
        assert response["pagination"] == {
            "page": 2,
            "limit": 10,
            "total": 1,
            "total_pages": 1,
        }

    @pytest.mark.asyncio
    async def test_export_json_with_date_filters(self):
        log = mock.Mock()
        log.to_dict.return_value = {"id": "2"}
        db = _db([_result(scalars=[log])])

        response = await export_activity_logs(
            format="json",
            user_id=str(uuid.uuid4()),
            action="credits.grant",
            target_type="user",
            from_date=datetime(2024, 1, 1, tzinfo=UTC),
            to_date=datetime(2024, 6, 1, tzinfo=UTC),
            limit=500,
            current_user=_admin_user(),
            db=db,
        )

        assert response == {"logs": [{"id": "2"}], "count": 1}


# ----------------------------------------------------------------------
# Email endpoints
# ----------------------------------------------------------------------


class TestEmailStatus:
    @pytest.mark.asyncio
    async def test_status_connected_with_login(self):
        service = mock.Mock(
            enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=587,
            use_tls=False,
            verify_certs=True,
            smtp_user="user",
            smtp_password="secret",
        )
        smtp = mock.AsyncMock()
        with (
            mock.patch("app.services.email_service.EmailService", return_value=service),
            mock.patch("aiosmtplib.SMTP", return_value=smtp),
        ):
            response = await get_email_status(current_user=_admin_user())

        smtp.connect.assert_awaited_once()
        smtp.login.assert_awaited_once_with("user", "secret")
        smtp.quit.assert_awaited_once()
        assert response["status"] == "connected"
        assert response["host"] == "smtp.example.com"

    @pytest.mark.asyncio
    async def test_test_email_not_configured(self):
        service = mock.Mock(enabled=False)
        with mock.patch("app.services.email_service.EmailService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await send_test_email(
                    EmailTestRequest(to_email="a@b.c"), current_user=_admin_user()
                )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_test_email_no_recipient(self):
        service = mock.Mock(enabled=True)
        admin = _admin_user()
        admin.email = None
        with mock.patch("app.services.email_service.EmailService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await send_test_email(EmailTestRequest(to_email=None), current_user=admin)
        assert exc_info.value.status_code == 400
        assert "No recipient" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_test_email_send_failure(self):
        service = mock.AsyncMock(
            enabled=True, smtp_host="smtp.example.com", smtp_port=25
        )
        service.send_email.return_value = {"success": False, "error": "relay denied"}
        with mock.patch("app.services.email_service.EmailService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await send_test_email(
                    EmailTestRequest(to_email="a@b.c"), current_user=_admin_user()
                )
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_test_email_success(self):
        service = mock.AsyncMock(
            enabled=True, smtp_host="smtp.example.com", smtp_port=25
        )
        service.send_email.return_value = {"success": True}
        with mock.patch("app.services.email_service.EmailService", return_value=service):
            response = await send_test_email(
                EmailTestRequest(to_email=None), current_user=_admin_user()
            )
        assert response["success"] is True
        assert response["recipient"] == "admin@example.com"


# ----------------------------------------------------------------------
# Refresh volume sizes
# ----------------------------------------------------------------------


class TestRefreshVolumeSizes:
    @pytest.mark.asyncio
    async def test_mixed_refresh_results(self):
        v_ok = mock.Mock(id=uuid.uuid4(), name="vol_ok", size_bytes=0)
        v_err = mock.Mock(id=uuid.uuid4(), name="vol_err")
        v_none = mock.Mock(id=uuid.uuid4(), name="vol_none")
        db = _db([_result(scalars=[v_ok, v_err, v_none])])

        service = mock.AsyncMock()
        service.measure_volume_size.side_effect = [
            (12345, "du"),
            RuntimeError("xfs quota failed"),
            (None, "du"),
        ]
        with mock.patch("app.api.admin.VolumeService", return_value=service):
            response = await admin_refresh_volume_sizes(
                current_user=_admin_user(), db=db
            )

        assert response["refreshed"] == 1
        assert v_ok.size_bytes == 12345
        failed = {f["volume_id"]: f["error"] for f in response["failed"]}
        assert failed[str(v_err.id)] == "xfs quota failed"
        assert failed[str(v_none.id)] == "could not measure size"
        db.commit.assert_awaited_once()


# ----------------------------------------------------------------------
# Health monitoring
# ----------------------------------------------------------------------


def _health_db(*, db_fails=False):
    """DB mock for get_health_monitoring with no running servers."""
    results = []
    if db_fails:
        results.append(RuntimeError("connection refused"))
    else:
        results.append(_result())
    # total_running=0 -> server id page empty -> latest checks skipped
    results.append(_result(scalar=0))  # total running servers
    results.append(_result(all_rows=[]))  # paginated server ids
    results.append(_result(all_rows=[]))  # summary status counts
    results.append(_result(all_rows=[]))  # recent restart events
    return _db(results)


def _psutil_patches():
    disk_usage = mock.Mock(percent=42.0, total=1000, used=420, free=580)
    partitions = [
        mock.Mock(mountpoint="/", fstype="xfs"),
        mock.Mock(mountpoint="/data/volumes", fstype="ext4"),
    ]
    mem = mock.Mock(percent=55.0, total=2048, available=1024, used=1024)
    return (
        mock.patch("psutil.disk_usage", return_value=disk_usage),
        mock.patch("psutil.disk_partitions", return_value=partitions),
        mock.patch("psutil.cpu_count", side_effect=lambda logical=True: 8 if logical else 4),
        mock.patch("psutil.cpu_freq", return_value=mock.Mock(current=2400.0)),
        mock.patch("psutil.cpu_percent", return_value=3.5),
        mock.patch("psutil.virtual_memory", return_value=mem),
        mock.patch("psutil.getloadavg", return_value=(0.1, 0.2, 0.3)),
    )


class TestHealthMonitoring:
    @pytest.mark.asyncio
    async def test_degraded_services_and_resource_details(self):
        """Partition issues degrade status; disk fstype detection is exercised."""
        db = _health_db()

        redis_client = mock.AsyncMock()
        container_client = mock.AsyncMock()
        container_client.version.return_value = {
            "Version": "5.0.0",
            "Components": [{"Name": "Podman Engine"}],
        }
        email_service = mock.Mock(enabled=False)

        pm = mock.AsyncMock()
        pm.PARTITION_CONFIG = ["activity_logs"]
        pm.list_partitions.return_value = [{"partition_name": "activity_logs_default"}]

        p_disk, p_parts, p_ccount, p_cfreq, p_cpct, p_vmem, p_load = _psutil_patches()
        with (
            p_disk,
            p_parts,
            p_ccount,
            p_cfreq,
            p_cpct,
            p_vmem,
            p_load,
            mock.patch("redis.asyncio.from_url", return_value=redis_client),
            mock.patch("app.container.client.container_client", container_client),
            mock.patch(
                "app.services.email_service.EmailService", return_value=email_service
            ),
            mock.patch("app.db.partitioning.PartitionManager", return_value=pm),
            mock.patch("app.config.settings.volume_storage_path", "/data/volumes"),
        ):
            response = await get_health_monitoring(
                page=1,
                limit=20,
                status_filter=None,
                search="web",
                current_user=_admin_user(),
                db=db,
            )

        system = response["system"]
        assert system["status"] == "degraded"
        assert system["services"]["database"]["status"] == "healthy"
        assert system["services"]["redis"]["status"] == "healthy"
        assert system["services"]["containers"]["runtime"] == "Podman"
        assert system["services"]["smtp"]["status"] == "disabled"
        assert system["services"]["partitions"]["status"] == "unhealthy"
        assert "no monthly partitions" in system["services"]["partitions"]["error"]
        assert system["resources"]["disk"]["fstype"] == "xfs"
        assert system["resources"]["container_disk"]["fstype"] == "ext4"
        assert response["containers"]["pagination"]["total"] == 0
        assert response["recent_restarts"] == []

    @pytest.mark.asyncio
    async def test_all_dependency_failures_degrade(self):
        """Every external check fails; resource fallback kicks in."""
        db = _health_db(db_fails=True)

        container_client = mock.AsyncMock()
        container_client.connect.side_effect = RuntimeError("socket missing")

        email_service = mock.Mock(
            enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=25,
            use_tls=False,
            verify_certs=True,
        )
        smtp = mock.AsyncMock()
        smtp.connect.side_effect = RuntimeError("smtp unreachable")

        with (
            mock.patch(
                "redis.asyncio.from_url", side_effect=RuntimeError("redis gone")
            ),
            mock.patch("app.container.client.container_client", container_client),
            mock.patch(
                "app.services.email_service.EmailService", return_value=email_service
            ),
            mock.patch("aiosmtplib.SMTP", return_value=smtp),
            mock.patch(
                "app.db.partitioning.PartitionManager",
                side_effect=RuntimeError("partition query failed"),
            ),
            mock.patch("psutil.disk_usage", side_effect=RuntimeError("no /proc")),
        ):
            response = await get_health_monitoring(
                page=1,
                limit=20,
                status_filter=None,
                search=None,
                current_user=_admin_user(),
                db=db,
            )

        system = response["system"]
        assert system["status"] == "degraded"
        assert "connection refused" in system["services"]["database"]["error"]
        assert "redis gone" in system["services"]["redis"]["error"]
        assert "socket missing" in system["services"]["containers"]["error"]
        assert "smtp unreachable" in system["services"]["smtp"]["error"]
        assert "partition query failed" in system["services"]["partitions"]["error"]
        # Resource fallback zeros everything out
        assert system["resources"]["cpu"]["count"] == 0
        assert system["resources"]["disk"]["path"] == "/"

    @pytest.mark.asyncio
    async def test_healthy_smtp_and_partitions_with_fs_detection_errors(self):
        """Healthy SMTP/partition branches; fstype detection errors are swallowed."""
        db = _health_db()

        redis_client = mock.AsyncMock()
        container_client = mock.AsyncMock()
        container_client.version.return_value = {"Version": "5.0.0", "Components": []}

        email_service = mock.Mock(
            enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=465,
            use_tls=True,
            verify_certs=True,
        )
        smtp = mock.AsyncMock()

        pm = mock.AsyncMock()
        pm.PARTITION_CONFIG = ["activity_logs"]
        pm.list_partitions.return_value = [{"partition_name": "activity_logs_y2026m7"}]

        disk_usage = mock.Mock(percent=42.0, total=1000, used=420, free=580)
        mem = mock.Mock(percent=55.0, total=2048, available=1024, used=1024)
        with (
            mock.patch("psutil.disk_usage", return_value=disk_usage),
            mock.patch(
                "psutil.disk_partitions", side_effect=RuntimeError("partitions unreadable")
            ),
            mock.patch("psutil.cpu_count", return_value=4),
            mock.patch("psutil.cpu_freq", return_value=None),
            mock.patch("psutil.cpu_percent", return_value=3.5),
            mock.patch("psutil.virtual_memory", return_value=mem),
            mock.patch("psutil.getloadavg", return_value=(0.1, 0.2, 0.3)),
            mock.patch("redis.asyncio.from_url", return_value=redis_client),
            mock.patch("app.container.client.container_client", container_client),
            mock.patch(
                "app.services.email_service.EmailService", return_value=email_service
            ),
            mock.patch("aiosmtplib.SMTP", return_value=smtp),
            mock.patch("app.db.partitioning.PartitionManager", return_value=pm),
            mock.patch("app.config.settings.volume_storage_path", "/data/volumes"),
        ):
            response = await get_health_monitoring(
                page=1,
                limit=20,
                status_filter=None,
                search=None,
                current_user=_admin_user(),
                db=db,
            )

        system = response["system"]
        assert system["status"] == "healthy"
        smtp.connect.assert_awaited_once()
        smtp.starttls.assert_awaited_once()
        smtp.quit.assert_awaited_once()
        assert system["services"]["smtp"]["status"] == "healthy"
        assert system["services"]["containers"]["runtime"] == "Containers"
        assert system["services"]["partitions"]["status"] == "healthy"
        # fstype detection failed gracefully in both disk entries
        assert system["resources"]["disk"]["fstype"] is None
        assert system["resources"]["container_disk"]["fstype"] is None
