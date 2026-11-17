# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.time_utils import utc_now
from app.schemas.server_launch import NormalizedLaunchRequest
from app.services.environment_revision_service import ConfigurationChanged, RevisionUnavailable
from app.services.server_launch_service import LaunchError
from app.services.server_queue_dispatch_service import ServerQueueDispatchService
from app.services.volume_operation_service import VolumeOperationError


def candidate(**overrides):
    payload = {
        "name": "research",
        "plan_id": str(uuid4()),
        "environment_id": str(uuid4()),
        "volume_mounts": [
            {
                "volume_id": "",
                "mount_path": "/home/researcher",
                "mode": "read_write",
                "max_size_bytes": 1024,
                "is_primary": True,
            }
        ],
    }
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        request_payload=payload,
        request_version=1,
        revision_id=uuid4(),
        priority=0,
        requested_at=utc_now(),
        **overrides,
    )


@pytest.fixture
def setup_dispatcher():
    context = MagicMock()
    context.__aenter__ = AsyncMock()
    context.__aexit__ = AsyncMock(return_value=False)
    rows = MagicMock()
    rows.all.return_value = []
    db = MagicMock(
        new=set(),
        dirty=set(),
        deleted=set(),
        in_transaction=MagicMock(return_value=False),
        rollback=AsyncMock(),
        begin=MagicMock(return_value=context),
        scalars=AsyncMock(return_value=rows),
        scalar=AsyncMock(return_value=None),
        flush=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    launch = MagicMock(reserve=AsyncMock(), provision=AsyncMock(), resolve_revision=AsyncMock())
    expire = AsyncMock(return_value=0)
    with (
        patch(
            "app.services.server_queue_dispatch_service.ServerLaunchService", return_value=launch
        ),
        patch(
            "app.services.server_queue_dispatch_service.ServerQueueService.expire_pending", expire
        ),
        patch("app.services.server_queue_dispatch_service.acquire_admission_lock", AsyncMock()),
    ):
        yield SimpleNamespace(
            service=ServerQueueDispatchService(db, MagicMock()),
            db=db,
            launch=launch,
            rows=rows,
            expire=expire,
        )


@pytest.mark.asyncio
async def test_empty_scan_expires_pending_only_and_bounds_order(setup_dispatcher):
    setup = setup_dispatcher
    setup.expire.return_value = 3
    result = await setup.service.dispatch()
    assert result.expired == 3
    assert result.scanned == 0
    statement = setup.db.scalars.call_args.args[0]
    sql = str(statement)
    assert "DESC, server_queue.requested_at ASC NULLS LAST, server_queue.id ASC" in sql
    assert 20 in statement.compile().params.values()
    assert statement.get_execution_options()["populate_existing"]
    setup.launch.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -1, 101, True, "20"])
async def test_invalid_scan_bound_rejected_without_database_io(setup_dispatcher, size):
    setup = setup_dispatcher
    with pytest.raises(ValueError, match="between 1 and 100"):
        await setup.service.dispatch(batch_size=size)
    setup.db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_fit_preserves_payload_and_immutable_revision(setup_dispatcher):
    setup = setup_dispatcher
    first, second = candidate(), candidate()
    setup.rows.all.return_value = [first, second]
    reservation = SimpleNamespace(queue_id=second.id, claim_token=uuid4())
    setup.launch.reserve.side_effect = [None, reservation]
    result = await setup.service.dispatch(batch_size=2)
    assert result.scanned == 2
    assert result.waiting == 1
    assert result.started == 1
    calls = setup.launch.reserve.await_args_list
    assert calls[1].args[0] == second.user_id
    assert isinstance(calls[1].args[1], NormalizedLaunchRequest)
    assert calls[1].args[1].volume_mounts[0].volume_id == ""
    assert calls[1].args[1].volume_mounts[0].max_size_bytes == 1024
    assert calls[1].args[2] == second.revision_id
    assert calls[1].kwargs == {"queue_id": second.id}
    setup.launch.provision.assert_awaited_once_with(reservation)
    setup.launch.resolve_revision.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("request_payload", None),
        ("request_payload", {}),
        ("request_version", 0),
        ("request_version", 2),
        ("revision_id", None),
    ],
)
async def test_legacy_incomplete_intent_cancelled_with_resubmit_reason(
    setup_dispatcher, field, value
):
    setup = setup_dispatcher
    row = candidate()
    setattr(row, field, value)
    setup.rows.all.return_value = [row]
    result = await setup.service.dispatch()
    assert result.cancelled == 1
    params = setup.db.execute.call_args.args[0].compile().params
    assert params["status"] == "cancelled"
    assert params["reason_code"] == "configuration_changed"
    assert "server_queue.status =" in str(setup.db.execute.call_args.args[0])
    setup.launch.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_preserved_intent_fails_before_provisioning(setup_dispatcher):
    setup = setup_dispatcher
    row = candidate()
    row.request_payload["volume_mounts"][0]["mount_path"] = "../host"
    setup.rows.all.return_value = [row]
    result = await setup.service.dispatch()
    assert result.failed == 1
    params = setup.db.execute.call_args.args[0].compile().params
    assert params["status"] == "failed"
    assert params["reason_code"] == "configuration_changed"
    setup.launch.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code",
    [
        (LaunchError("permission_revoked", 403), "permission_revoked"),
        (LaunchError("configuration_changed"), "configuration_changed"),
        (LaunchError("quota_exceeded", 429), "quota_exceeded"),
        (RevisionUnavailable("private raw details"), "revision_unavailable"),
        (ConfigurationChanged("private raw details"), "configuration_changed"),
    ],
)
async def test_definitive_policy_rejection_only_fails_still_pending(setup_dispatcher, error, code):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate()]
    setup.launch.reserve.side_effect = error
    result = await setup.service.dispatch()
    assert result.failed == 1
    statement = setup.db.execute.call_args.args[0]
    params = statement.compile().params
    assert params["status"] == "failed"
    assert params["reason_code"] == code
    assert "private raw details" not in str(params)
    setup.launch.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_claim_race_never_fails_runtime(setup_dispatcher):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate()]
    setup.launch.reserve.side_effect = LaunchError("launch_in_progress")
    result = await setup.service.dispatch()
    assert result.skipped == 1
    assert result.failed == 0
    setup.db.execute.assert_not_awaited()
    setup.launch.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_conditional_failure_that_lost_to_claim_is_skipped(setup_dispatcher):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate()]
    setup.launch.reserve.side_effect = LaunchError("permission_revoked", 403)
    setup.db.execute.return_value = SimpleNamespace(rowcount=0)
    result = await setup.service.dispatch()
    assert result.skipped == 1
    assert result.failed == 0


@pytest.mark.asyncio
async def test_volume_operation_conflict_remains_waiting(setup_dispatcher):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate()]
    setup.launch.reserve.side_effect = VolumeOperationError("volume_busy")
    result = await setup.service.dispatch()
    assert result.waiting == 1
    params = setup.db.execute.call_args.args[0].compile().params
    assert params["status"] == "pending"
    assert params["reason_code"] == "volume_busy"


@pytest.mark.asyncio
async def test_unknown_admission_failure_remains_pending_and_scan_continues(setup_dispatcher):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate(), candidate()]
    setup.launch.reserve.side_effect = [RuntimeError("database unreachable"), None]
    result = await setup.service.dispatch()
    assert result.skipped == 1
    assert result.waiting == 1
    setup.db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("runtime disconnected"), LaunchError("configuration_changed")]
)
async def test_provision_errors_never_release_claim_or_mark_failed(setup_dispatcher, error):
    setup = setup_dispatcher
    row = candidate()
    reservation = SimpleNamespace(queue_id=row.id, claim_token=uuid4())
    setup.rows.all.return_value = [row]
    setup.launch.reserve.return_value = reservation
    setup.launch.provision.side_effect = error
    result = await setup.service.dispatch()
    assert result.recovery_required == 1
    assert result.failed == 0
    statement = setup.db.execute.call_args.args[0]
    params = statement.compile().params
    assert params["reason_code"] == "recovery_required"
    assert "status" not in params
    assert row.id in params.values()
    assert reservation.claim_token in params.values()
    assert "server_queue.status =" in str(statement)


@pytest.mark.asyncio
async def test_cancellation_after_reservation_preserves_uncertain_runtime(setup_dispatcher):
    setup = setup_dispatcher
    row = candidate()
    setup.rows.all.return_value = [row]
    setup.launch.reserve.return_value = SimpleNamespace(queue_id=row.id, claim_token=uuid4())
    setup.launch.provision.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await setup.service.dispatch()
    params = setup.db.execute.call_args.args[0].compile().params
    assert params["reason_code"] == "recovery_required"
    assert "status" not in params


@pytest.mark.asyncio
async def test_cancellation_during_reserve_propagates_without_provision(setup_dispatcher):
    setup = setup_dispatcher
    setup.rows.all.return_value = [candidate()]
    setup.launch.reserve.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await setup.service.dispatch()
    setup.launch.provision.assert_not_awaited()
    setup.db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_dirty_session_rejected_before_scan(setup_dispatcher):
    setup = setup_dispatcher
    setup.db.dirty = {object()}
    with pytest.raises(RuntimeError, match="clean session"):
        await setup.service.dispatch()
    setup.db.scalars.assert_not_awaited()
