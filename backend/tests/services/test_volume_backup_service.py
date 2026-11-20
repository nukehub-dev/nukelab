# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Recovery reservations survive failures and never authorize ambiguous cleanup."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.time_utils import utc_now
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.services.volume_backup_service import BackupError, RecoveryPolicy, VolumeBackupService
from app.services.volume_operation_service import VolumeOperationError, acquire_volume_operations
from app.services.volume_recovery_runtime import RuntimeRecoveryError


@pytest.fixture
def recovery(db_session):
    metadata = {
        "sha256": "a" * 64,
        "compressed_bytes": 100,
        "logical_bytes": 200,
        "member_count": 3,
        "executor_terminated": True,
    }
    runtime = Mock()
    runtime.check_helper = AsyncMock()
    runtime.assert_detached = AsyncMock()
    runtime.capture = AsyncMock(return_value=metadata)
    runtime.restore = AsyncMock(return_value=metadata)
    runtime.delete_artifact = AsyncMock()
    runtime.available_bytes.return_value = 10**12
    policy = RecoveryPolicy(30, 20, 10**10, 10**11, 1024**2, 10)
    return VolumeBackupService(db_session, runtime, policy)


async def source(db, owner_id, **overrides):
    volume = Volume(
        id=uuid4(),
        name="private-" + uuid4().hex,
        display_name="Private Ω",
        owner_id=owner_id,
        visibility="private",
        status="active",
        max_size_bytes=1024**2,
        labels={"was_home_volume": True},
        **overrides,
    )
    db.add(volume)
    await db.commit()
    return volume.id


async def complete(db, recovery, owner_id):
    vid = await source(db, owner_id)
    row = await recovery.reserve_backup(owner_id, vid)
    return vid, await recovery.execute_backup(row.id)


@pytest.mark.asyncio
async def test_intent_is_committed_before_runtime_and_redelivery_is_idempotent(
    db_session, test_user, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    operation = uuid4()

    async def detached(name):
        assert not db_session.in_transaction()

    recovery.runtime.assert_detached.side_effect = detached
    first = await recovery.reserve_backup(owner, vid, operation, "Recovery point")
    assert first.status == "pending"
    second = await recovery.reserve_backup(owner, vid, operation, "Recovery point")
    assert second.id == first.id
    with pytest.raises(BackupError, match="operation_conflict"):
        await recovery.reserve_backup(owner, vid, operation, "Different request")
    done = await recovery.execute_backup(operation)
    assert done.status == "completed" and done.can_restore
    assert (await recovery.execute_backup(operation)).id == operation
    recovery.runtime.capture.assert_awaited_once()
    guard = await db_session.get(VolumeOperation, (operation, vid))
    assert guard.state == "succeeded"
    assert "backup_path" not in done.model_dump() and "sha256" not in done.model_dump()


@pytest.mark.asyncio
async def test_restore_has_stable_new_identity_and_pins_retention(db_session, test_user, recovery):
    owner = test_user.id
    source_id, backup = await complete(db_session, recovery, owner)
    operation = uuid4()
    restored = await recovery.reserve_restore(owner, backup.id, "Recovered", 1024**2, operation)
    assert restored.status == "pending" and restored.destination_volume_id != source_id
    same = await recovery.reserve_restore(owner, backup.id, "Recovered", 1024**2, operation)
    assert same.destination_volume_id == restored.destination_volume_id
    with pytest.raises(BackupError, match="backup_in_progress"):
        await recovery.request_delete(owner, backup.id)
    row = await db_session.get(VolumeBackup, backup.id)
    row.expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    assert not await recovery.expire_backup(backup.id)
    done = await recovery.execute_restore(operation)
    assert done.status == "completed"
    assert (
        await recovery.execute_restore(operation)
    ).destination_volume_id == restored.destination_volume_id
    destination = await db_session.get(Volume, restored.destination_volume_id)
    assert destination.status == "active" and destination.visibility == "private"
    assert destination.labels["was_home_volume"] is True
    assert destination.size_bytes == 200
    recovery.runtime.restore.assert_awaited_once()
    assert await recovery.expire_backup(backup.id)
    assert (await recovery.get_backup(owner, backup.id)).status == "deleted"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminated", [False, True])
async def test_runtime_failure_retains_guard_without_termination_proof(
    db_session, test_user, recovery, terminated
):
    owner = test_user.id
    vid = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, vid)
    recovery.runtime.capture.side_effect = RuntimeRecoveryError(
        "helper_failed", executor_terminated=terminated, artifacts_removed=terminated
    )
    result = await recovery.execute_backup(pending.id)
    assert result.status == ("failed" if terminated else "recovery_required")
    guard = await db_session.get(VolumeOperation, (pending.id, vid))
    assert guard.state == ("failed" if terminated else "recovery_required")
    await db_session.rollback()
    async with db_session.begin():
        if terminated:
            await acquire_volume_operations(
                db_session, volume_ids=[vid], owner_id=owner, operation_id=uuid4(), kind="writer"
            )
        else:
            with pytest.raises(VolumeOperationError, match="volume_busy"):
                await acquire_volume_operations(
                    db_session,
                    volume_ids=[vid],
                    owner_id=owner,
                    operation_id=uuid4(),
                    kind="writer",
                )


@pytest.mark.asyncio
async def test_preflight_attachment_failure_does_not_launch_helper(db_session, test_user, recovery):
    owner = test_user.id
    vid = await source(db_session, owner)
    recovery.runtime.assert_detached.side_effect = RuntimeRecoveryError(
        "volume_attached", executor_terminated=True
    )
    with pytest.raises(BackupError):
        await recovery.reserve_backup(owner, vid)
    row = await db_session.scalar(select(VolumeBackup))
    assert row.status == "failed" and row.reserved_bytes == 0
    assert row.reason_code == "volume_busy"
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_worker_permission_fails_pending_without_leaking_guard(
    db_session, test_user, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, vid)
    actor = await db_session.get(type(test_user), owner)
    actor.is_active = False
    await db_session.commit()
    result = await recovery.execute_backup(pending.id)
    assert result.status == "failed" and result.reason_code == "permission_revoked"
    assert (await db_session.get(VolumeOperation, (pending.id, vid))).state == "failed"
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_quota_rejection_has_no_intent_or_runtime_side_effect(
    db_session, test_user, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    recovery.runtime.available_bytes.return_value = 0
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_backup(owner, vid)
    assert await db_session.scalar(select(func.count()).select_from(VolumeBackup)) == 0
    assert await db_session.scalar(select(func.count()).select_from(VolumeOperation)) == 0
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_deletion_failure_retains_storage_and_retry_cleans_after_proof(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    await recovery.request_delete(owner, backup.id)
    recovery.runtime.delete_artifact.side_effect = RuntimeError("/secret/host/path")
    result = await recovery.execute_delete(backup.id)
    assert result.status == "delete_failed" and "/secret" not in result.model_dump_json()
    row = await db_session.get(VolumeBackup, backup.id)
    assert row.size_bytes == 100
    await db_session.rollback()
    recovery.runtime.delete_artifact.side_effect = None
    await recovery.request_delete(owner, backup.id)
    assert (await recovery.execute_delete(backup.id)).status == "deleted"
    await recovery.execute_delete(backup.id)
    assert recovery.runtime.delete_artifact.await_count == 2


@pytest.mark.asyncio
async def test_source_deletion_preserves_owner_restore_and_foreign_ids_are_hidden(
    db_session, test_user, admin_user, recovery
):
    owner, other = test_user.id, admin_user.id
    vid, backup = await complete(db_session, recovery, owner)
    with pytest.raises(BackupError, match="backup_not_found"):
        await recovery.get_backup(other, backup.id)
    source_volume = await db_session.get(Volume, vid)
    await db_session.execute(delete(VolumeOperation).where(VolumeOperation.volume_id == vid))
    await db_session.delete(source_volume)
    await db_session.commit()
    saved = await recovery.get_backup(owner, backup.id)
    assert saved.source_volume_id is None and saved.can_restore
    restored = await recovery.reserve_restore(owner, backup.id, "Retained", 1024**2)
    with pytest.raises(BackupError, match="restore_not_found"):
        await recovery.get_restore(other, restored.id)
    assert (await recovery.list_backups(other)).total == 0
    assert (await recovery.list_restores(other)).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sha,logical,count", [("not-a-digest", 200, 3), ("a" * 64, 2**40, 3), ("a" * 64, 200, -1)]
)
async def test_malformed_helper_completion_never_publishes_backup(
    db_session, test_user, recovery, sha, logical, count
):
    owner = test_user.id
    vid = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, vid)
    recovery.runtime.capture.return_value = {
        "sha256": sha,
        "logical_bytes": logical,
        "compressed_bytes": 100,
        "member_count": count,
        "executor_terminated": True,
    }
    result = await recovery.execute_backup(pending.id)
    assert result.status == "recovery_required" and not result.can_restore
    assert (await db_session.get(VolumeOperation, (pending.id, vid))).state == "recovery_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminated", [True, False])
async def test_restore_failure_keeps_destination_unmountable_and_retains_unknown_pin(
    db_session, test_user, recovery, terminated
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    pending = await recovery.reserve_restore(owner, backup.id, "Failed copy", 1024**2)
    recovery.runtime.restore.side_effect = RuntimeRecoveryError(
        "artifact_corrupt", executor_terminated=terminated, artifacts_removed=terminated
    )
    result = await recovery.execute_restore(pending.id)
    assert result.status == ("failed" if terminated else "recovery_required")
    destination = await db_session.get(Volume, pending.destination_volume_id)
    assert destination.status == ("restore_failed" if terminated else "restoring")
    operation = await db_session.get(VolumeOperation, (pending.id, pending.destination_volume_id))
    assert operation.state == ("failed" if terminated else "recovery_required")
    if terminated:
        assert (await recovery.request_delete(owner, backup.id)).status == "deleting"
    else:
        with pytest.raises(BackupError, match="backup_in_progress"):
            await recovery.request_delete(owner, backup.id)


@pytest.mark.asyncio
async def test_restore_quota_and_checksum_failures_never_activate_destination(
    db_session, test_user, recovery, monkeypatch
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    before = await db_session.scalar(select(func.count()).select_from(Volume))
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_restore(owner, backup.id, "Too small", 100)
    monkeypatch.setattr(
        "app.services.quota_service.QuotaService.check_volume_creation_allowed",
        AsyncMock(return_value={"allowed": False}),
    )
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_restore(owner, backup.id, "Too large", 1024**2)
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == before
    monkeypatch.setattr(
        "app.services.quota_service.QuotaService.check_volume_creation_allowed",
        AsyncMock(return_value={"allowed": True}),
    )
    pending = await recovery.reserve_restore(owner, backup.id, "Corrupt copy", 1024**2)
    recovery.runtime.restore.return_value = {
        **recovery.runtime.capture.return_value,
        "sha256": "b" * 64,
    }
    result = await recovery.execute_restore(pending.id)
    assert result.status == "recovery_required" and result.reason_code == "artifact_corrupt"
    assert (await db_session.get(Volume, pending.destination_volume_id)).status == "restoring"


@pytest.mark.asyncio
async def test_expired_and_legacy_backups_are_never_restore_points(db_session, test_user, recovery):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    row = await db_session.get(VolumeBackup, backup.id)
    row.expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    assert not (await recovery.get_backup(owner, backup.id)).can_restore
    with pytest.raises(BackupError, match="backup_expired"):
        await recovery.reserve_restore(owner, backup.id, "Expired", 1024**2)
    row = await db_session.get(VolumeBackup, backup.id)
    row.format_version = None
    await db_session.commit()
    legacy = await recovery.get_backup(owner, backup.id)
    assert legacy.reason_code == "unsupported_backup" and not legacy.can_delete
    with pytest.raises(BackupError, match="unsupported_backup"):
        await recovery.reserve_restore(owner, backup.id, "Legacy", 1024**2)
    assert not await recovery.expire_backup(backup.id)
    with pytest.raises(BackupError, match="unsupported_backup"):
        await recovery.request_delete(owner, backup.id)


@pytest.mark.asyncio
async def test_owner_and_global_storage_accounting_include_pending_restores(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    pending = await recovery.reserve_restore(owner, backup.id, "Reserved", 1024**2)
    row = await db_session.get(VolumeRestore, pending.id)
    reservation = row.reserved_bytes
    assert reservation > 0
    await db_session.rollback()
    recovery.policy = RecoveryPolicy(30, 20, reservation + 100, 10**11, 1024**2, 10)
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_restore(owner, backup.id, "Another", 1024**2)
    recovery.policy = RecoveryPolicy(30, 20, 10**11, reservation + 100, 1024**2, 10)
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_restore(owner, backup.id, "Another", 1024**2)
    recovery.runtime.restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_capability_failures_remain_sanitized_and_metadata_readable(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    recovery.runtime.check_helper.side_effect = RuntimeError("/private/backup/root")
    capability = await recovery.capability()
    assert not capability.enabled and capability.reason_code == "storage_unavailable"
    saved = await recovery.get_backup(owner, backup.id)
    assert not saved.can_restore and not saved.can_delete
    assert "/private" not in saved.model_dump_json()
    with pytest.raises(BackupError, match="storage_unavailable"):
        await recovery.reserve_restore(owner, backup.id, "Unavailable", 1024**2)
    recovery.runtime.check_helper.side_effect = RuntimeRecoveryError("helper_unavailable")
    assert (await recovery.capability()).reason_code == "helper_unavailable"
    recovery.runtime = None
    assert (await recovery.capability()).reason_code == "storage_unavailable"


@pytest.mark.asyncio
async def test_source_writer_intent_competes_atomically_with_backup(
    db_session, test_user, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    writer = uuid4()
    async with db_session.begin():
        await acquire_volume_operations(
            db_session, volume_ids=[vid], owner_id=owner, operation_id=writer, kind="writer"
        )
    eligible = await recovery.eligibility(owner, vid)
    assert not eligible.eligible and eligible.reason_code == "volume_busy"
    with pytest.raises(BackupError, match="volume_busy"):
        await recovery.reserve_backup(owner, vid)
    assert await db_session.scalar(select(func.count()).select_from(VolumeBackup)) == 0
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_disappearance_and_source_limit_fail_before_persisting_work(
    db_session, test_user, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    recovery.runtime.available_bytes.side_effect = RuntimeError("private disk")
    with pytest.raises(BackupError) as rejected:
        await recovery.reserve_backup(owner, vid)
    assert rejected.value.status_code == 503 and rejected.value.code == "storage_unavailable"
    recovery.runtime.available_bytes.side_effect = None
    recovery.policy = RecoveryPolicy(30, 1, 10**10, 10**11, 1024**2, 10)
    pending = await recovery.reserve_backup(owner, vid)
    await recovery.execute_backup(pending.id)
    with pytest.raises(BackupError, match="quota_exceeded"):
        await recovery.reserve_backup(owner, vid)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["backup", "restore"])
async def test_cleanup_without_termination_cannot_release_storage_or_exclusion(
    db_session, test_user, recovery, kind
):
    owner = test_user.id
    if kind == "backup":
        volume_id = await source(db_session, owner)
        pending = await recovery.reserve_backup(owner, volume_id)
        model, executor = VolumeBackup, recovery.execute_backup
    else:
        _, backup = await complete(db_session, recovery, owner)
        pending = await recovery.reserve_restore(owner, backup.id, "Protected", 1024**2)
        volume_id = pending.destination_volume_id
        model, executor = VolumeRestore, recovery.execute_restore
    row = await db_session.get(model, pending.id)
    reservation = row.reserved_bytes
    await db_session.rollback()
    getattr(
        recovery.runtime, "capture" if kind == "backup" else "restore"
    ).side_effect = RuntimeRecoveryError(
        "helper_failed", executor_terminated=False, artifacts_removed=True
    )
    result = await executor(pending.id)
    assert result.status == "recovery_required"
    assert (await db_session.get(model, pending.id)).reserved_bytes == reservation
    assert (
        await db_session.get(VolumeOperation, (pending.id, volume_id))
    ).state == "recovery_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [True, False, RuntimeError("quota unavailable")])
async def test_restore_requires_configured_kernel_quota_before_activation(
    db_session, test_user, recovery, monkeypatch, outcome
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    pending = await recovery.reserve_restore(owner, backup.id, "Bounded copy", 1024**2)
    monkeypatch.setattr("app.services.volume_backup_service.settings.xfs_quota_enabled", True)
    setter = Mock(
        side_effect=outcome if isinstance(outcome, Exception) else None, return_value=outcome
    )
    monkeypatch.setattr("app.services.volume_backup_service.xfs_quota_service.set_quota", setter)
    result = await recovery.execute_restore(pending.id)
    volume = await db_session.get(Volume, pending.destination_volume_id)
    setter.assert_called_once_with(volume.name, 1024**2)
    if outcome is True:
        assert result.status == "completed" and volume.status == "active"
    else:
        assert result.status == "failed" and volume.status == "restore_failed"
        assert result.reason_code == "quota_enforcement_failed"
        assert "quota unavailable" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_revoked_restore_permission_releases_only_safe_preflight_resources(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    pending = await recovery.reserve_restore(owner, backup.id, "Revoked", 1024**2)
    actor = await db_session.get(type(test_user), owner)
    actor.is_active = False
    await db_session.commit()
    result = await recovery.execute_restore(pending.id)
    assert result.status == "failed" and result.reason_code == "permission_revoked"
    assert (await db_session.get(Volume, pending.destination_volume_id)).status == "restore_failed"
    assert (await db_session.get(VolumeRestore, pending.id)).reserved_bytes == 0
    recovery.runtime.restore.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility,status", [("public", "active"), ("private", "restoring")])
async def test_source_eligibility_and_reservation_share_private_offline_contract(
    db_session, test_user, recovery, visibility, status
):
    owner = test_user.id
    volume_id = await source(db_session, owner)
    volume = await db_session.get(Volume, volume_id)
    volume.visibility, volume.status = visibility, status
    await db_session.commit()
    expected = "private_volume_required" if visibility == "public" else "volume_busy"
    assert (await recovery.eligibility(owner, volume_id)).reason_code == expected
    with pytest.raises(BackupError, match=expected):
        await recovery.reserve_backup(owner, volume_id)
    recovery.runtime.assert_detached.assert_not_awaited()


@pytest.mark.asyncio
async def test_conflicting_restore_retries_and_late_fences_cannot_change_destination(
    db_session, test_user, admin_user, recovery
):
    owner, foreign = test_user.id, admin_user.id
    _, backup = await complete(db_session, recovery, owner)
    request_id = uuid4()
    pending = await recovery.reserve_restore(owner, backup.id, "Stable", 1024**2, request_id)
    for actor, name, size in (
        (foreign, "Stable", 1024**2),
        (owner, "Changed", 1024**2),
        (owner, "Stable", 2 * 1024**2),
    ):
        with pytest.raises(BackupError, match="operation_conflict"):
            await recovery.reserve_restore(actor, backup.id, name, size, request_id)
    with pytest.raises(BackupError, match="operation_conflict"):
        await recovery._finish_restore(pending.id, uuid4(), terminated=True, cleaned=True)
    destination = await db_session.get(Volume, pending.destination_volume_id)
    assert destination.status == "restoring" and destination.display_name == "Stable"
    assert await db_session.scalar(select(func.count()).select_from(VolumeRestore)) == 1
    recovery.runtime.restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_backup_fence_cannot_publish_or_release_another_executor(
    db_session, test_user, recovery
):
    owner = test_user.id
    volume_id = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, volume_id)
    with pytest.raises(BackupError, match="operation_conflict"):
        await recovery._finish_backup(
            pending.id, uuid4(), metadata=recovery.runtime.capture.return_value
        )
    row = await db_session.get(VolumeBackup, pending.id)
    assert row.status == "pending" and row.reserved_bytes > 0
    assert (await db_session.get(VolumeOperation, (pending.id, volume_id))).state == "reserved"
    assert (await recovery.execute_backup(pending.id)).status == "completed"


@pytest.mark.asyncio
async def test_pending_worker_rechecks_source_privacy_and_fails_without_runtime(
    db_session, test_user, recovery
):
    owner = test_user.id
    volume_id = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, volume_id)
    # Represents a legacy/out-of-band writer; normal sharing participates in the guard.
    volume = await db_session.get(Volume, volume_id)
    volume.visibility = "public"
    await db_session.commit()
    result = await recovery.execute_backup(pending.id)
    assert result.status == "failed" and result.reason_code == "private_volume_required"
    assert (await db_session.get(VolumeBackup, pending.id)).reserved_bytes == 0
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_pagination_filters_and_missing_ids_do_not_expose_other_rows(
    db_session, test_user, recovery
):
    owner = test_user.id
    source_id, first = await complete(db_session, recovery, owner)
    _, second = await complete(db_session, recovery, owner)
    await recovery.reserve_restore(owner, first.id, "First", 1024**2)
    await recovery.reserve_restore(owner, second.id, "Second", 1024**2)
    page = await recovery.list_backups(owner, page=2, page_size=1)
    assert page.total == 2 and len(page.items) == 1
    filtered = await recovery.list_backups(owner, volume_id=source_id)
    assert filtered.total == 1 and filtered.items[0].id == first.id
    restores = await recovery.list_restores(owner, page_size=1, backup_id=first.id)
    assert restores.total == 1 and restores.items[0].backup_id == first.id
    for lookup in (recovery.get_backup, recovery.get_restore):
        with pytest.raises(BackupError) as missing:
            await lookup(owner, uuid4())
        assert missing.value.status_code == 404
    for execute in (recovery.execute_backup, recovery.execute_restore, recovery.execute_delete):
        with pytest.raises(BackupError) as missing:
            await execute(uuid4())
        assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_claim_blocks_duplicate_delivery_and_new_restore(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, backup = await complete(db_session, recovery, owner)
    await recovery.request_delete(owner, backup.id)
    assert (await recovery.request_delete(owner, backup.id)).status == "deleting"
    with pytest.raises(BackupError, match="unsupported_backup"):
        await recovery.reserve_restore(owner, backup.id, "During cleanup", 1024**2)

    async def cleanup(backup_id):
        assert not db_session.in_transaction()
        duplicate = await recovery.execute_delete(backup_id)
        assert duplicate.status == "deleting"

    recovery.runtime.delete_artifact.side_effect = cleanup
    assert (await recovery.execute_delete(backup.id)).status == "deleted"
    assert (await recovery.request_delete(owner, backup.id)).status == "deleted"
    recovery.runtime.delete_artifact.assert_awaited_once()


@pytest.mark.asyncio
async def test_retention_ignores_recent_unknown_and_legacy_artifacts(
    db_session, test_user, recovery
):
    owner = test_user.id
    _, completed = await complete(db_session, recovery, owner)
    assert not await recovery.expire_backup(uuid4())
    assert not await recovery.expire_backup(completed.id)
    assert await recovery.retention_candidates() == []
    row = await db_session.get(VolumeBackup, completed.id)
    row.expires_at = utc_now() - timedelta(days=1)
    row.status = "recovery_required"
    await db_session.commit()
    assert not await recovery.expire_backup(completed.id)
    assert await recovery.retention_candidates() == []
    row.status = "completed"
    await db_session.commit()
    assert await recovery.retention_candidates(limit=1) == [completed.id]
    assert await recovery.expire_backup(completed.id)
    assert (await recovery.get_backup(owner, completed.id)).status == "deleted"


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [False, None, "true", 1])
async def test_helper_termination_proof_requires_exact_boolean(
    db_session, test_user, recovery, proof
):
    owner = test_user.id
    volume_id = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, volume_id)
    recovery.runtime.capture.return_value = {
        **recovery.runtime.capture.return_value,
        "executor_terminated": proof,
    }
    result = await recovery.execute_backup(pending.id)
    assert result.status == "recovery_required" and not result.can_restore
    assert (await db_session.get(VolumeBackup, pending.id)).reserved_bytes > 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("compressed_bytes", -1),
        ("compressed_bytes", 10**15),
        ("logical_bytes", True),
        ("member_count", 11),
    ],
)
def test_completion_metadata_is_bounded_and_strict(key, value):
    service = VolumeBackupService(
        Mock(), policy=RecoveryPolicy(30, 20, 10**10, 10**11, 1024**2, 10)
    )
    metadata = {
        "sha256": "a" * 64,
        "compressed_bytes": 100,
        "logical_bytes": 200,
        "member_count": 3,
    }
    metadata[key] = value
    with pytest.raises(BackupError, match="artifact_corrupt"):
        service._check_metadata(metadata, 1024**2)


@pytest.mark.asyncio
async def test_retention_page_skips_pinned_and_unsupported_backups(db_session, test_user, recovery):
    owner = test_user.id
    _, completed = await complete(db_session, recovery, owner)
    restore = await recovery.reserve_restore(owner, completed.id, "Pending restore", 1024**2)
    pinned = await db_session.get(VolumeBackup, completed.id)
    pinned.expires_at = utc_now() - timedelta(days=3)
    legacy = VolumeBackup(
        id=uuid4(),
        user_id=owner,
        volume_name="legacy",
        status="completed",
        expires_at=utc_now() - timedelta(days=2),
    )
    eligible = VolumeBackup(
        id=uuid4(),
        user_id=owner,
        volume_name="ready",
        status="completed",
        format_version=pinned.format_version,
        expires_at=utc_now() - timedelta(days=1),
    )
    db_session.add_all([legacy, eligible])
    await db_session.commit()
    # Filtering after LIMIT would let pinned or unsupported rows starve cleanup forever.
    assert await recovery.retention_candidates(limit=1) == [eligible.id]
    assert not await recovery.expire_backup(completed.id)
    assert (await recovery.get_restore(owner, restore.id)).status == "pending"
    await recovery.execute_restore(restore.id)
    assert await recovery.retention_candidates(limit=1) == [completed.id]
