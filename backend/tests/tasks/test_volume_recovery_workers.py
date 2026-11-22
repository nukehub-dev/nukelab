# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
"""Delivery failures retain persisted work; every executor owns its resources."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app import tasks
from app.config import settings
from tests.tasks.test_lifecycle_workers import database, result, worker_resources


@pytest.mark.parametrize("kind", ["backup", "restore", "delete"])
def test_delivery_selects_only_known_operations(kind):
    with patch.object(tasks.process_volume_recovery, "delay") as delivery:
        tasks.enqueue_volume_recovery(kind, "operation")
    delivery.assert_called_once_with(kind, "operation")
    with pytest.raises(ValueError):
        tasks.enqueue_volume_recovery("unknown", "operation")


@pytest.mark.parametrize("kind", ["backup", "restore", "delete"])
def test_execution_uses_owned_loop_and_returns_committed_result(kind):
    identifier = uuid.uuid4()
    db = database()
    output = Mock(status="pending")
    output.model_dump.return_value = {"id": str(identifier), "status": "pending"}
    service = SimpleNamespace(
        **{
            method: AsyncMock(return_value=output)
            for method in ("execute_backup", "execute_restore", "execute_delete")
        }
    )
    with (
        worker_resources(db) as owned,
        patch("app.services.volume_backup_service.VolumeBackupService", return_value=service),
    ):
        assert (
            tasks.process_volume_recovery.run(kind, str(identifier))
            == output.model_dump.return_value
        )
    getattr(service, "execute_" + kind).assert_awaited_once_with(identifier)
    assert owned.events[-1][1].is_closed()
    db.close.assert_awaited_once()
    owned.driver.close.assert_awaited_once()


def test_disabled_dispatch_opens_no_runtime_resources(monkeypatch):
    monkeypatch.setattr(settings, "volume_backup_storage_path", "")
    with patch("app.tasks.operation_resources") as resources:
        assert tasks.dispatch_volume_recovery.run() == "Volume recovery is disabled"
    resources.assert_not_called()


def test_dispatch_retries_pending_work_and_continues_after_broker_failure(monkeypatch):
    monkeypatch.setattr(settings, "volume_backup_storage_path", "/private")
    monkeypatch.setattr(settings, "volume_backup_host_path", "/host/private")
    backup, deletion, restore, expired = [uuid.uuid4() for _ in range(4)]
    db = database()
    db.execute.return_value = result(rows=[(backup, "pending"), (deletion, "deleting")])
    db.scalars = AsyncMock(return_value=[restore])
    service = SimpleNamespace(
        recover_stale_deletions=AsyncMock(return_value=0),
        retention_candidates=AsyncMock(return_value=[expired]),
        expire_backup=AsyncMock(side_effect=RuntimeError("busy")),
    )
    with (
        worker_resources(db) as owned,
        patch("app.services.volume_backup_service.VolumeBackupService", return_value=service),
        patch(
            "app.tasks.enqueue_volume_recovery", side_effect=[RuntimeError("broker"), None, None]
        ) as send,
    ):
        assert tasks.dispatch_volume_recovery.run() == "Dispatched 2 volume recovery operations"
    assert [call.args for call in send.call_args_list] == [
        ("backup", str(backup)),
        ("delete", str(deletion)),
        ("restore", str(restore)),
    ]
    service.recover_stale_deletions.assert_awaited_once_with(limit=20)
    db.rollback.assert_awaited_once()
    # Unknown/in-progress executors and claimed deletions are excluded before the page limit.
    query = str(db.execute.call_args.args[0])
    assert "helper_identity" in query
    owned.driver.close.assert_awaited_once()
