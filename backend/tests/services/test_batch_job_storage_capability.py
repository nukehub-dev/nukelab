# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Kernel storage-limit capability: truthful probe and fail-closed pilot gates."""

import uuid

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.batch_job import BatchJob
from app.schemas.batch_job import BatchJobSubmitRequest
from app.services import xfs_quota_service as xfs_module
from app.services.batch_job_admission_service import BatchJobAdmissionService
from app.services.batch_job_service import BatchJobService, JobError
from app.services.storage_capability_service import StorageCapabilityService
from app.services.xfs_quota_service import XfsQuotaProbe, XfsQuotaService, xfs_quota_service
from tests.services.test_batch_job_admission import (
    _make_job,
    _make_resources,
    admission_driver,
)


def _probe(available: bool, reason: str = "storage_unavailable") -> XfsQuotaProbe:
    return XfsQuotaProbe(available=available, reason=reason, path="/data/volumes")


def _patch_probe(monkeypatch, probe: XfsQuotaProbe) -> None:
    monkeypatch.setattr(xfs_quota_service, "probe_configured_storage", lambda: probe)


@pytest.fixture(autouse=True)
def pilot_settings(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", "")
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", False)


def test_xfs_probe_success_is_read_only(monkeypatch, tmp_path):
    service = XfsQuotaService()
    monkeypatch.setattr(settings, "xfs_quota_enabled", True)
    monkeypatch.setattr(settings, "volume_storage_path", str(tmp_path))
    monkeypatch.setattr(xfs_module.shutil, "which", lambda _name: "/usr/bin/xfs_quota")
    monkeypatch.setattr(service, "_is_xfs", lambda _path: True)
    monkeypatch.setattr(service, "_find_mountpoint", lambda _path: str(tmp_path))
    monkeypatch.setattr(service, "_mount_options", lambda _path: {"prjquota"})
    monkeypatch.setattr(xfs_module, "_has_effective_cap_sys_admin", lambda: True)
    monkeypatch.setattr(service, "_xfs_quota_can_query", lambda _path: True)
    monkeypatch.setattr(
        service,
        "_write_project_entry",
        lambda *_args: (_ for _ in ()).throw(AssertionError("probe must not write")),
    )
    monkeypatch.setattr(
        service,
        "_run_xfs_quota",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("probe must not mutate")),
    )

    probe = service.probe_configured_storage()

    assert probe.available is True
    assert probe.reason == "enforced"
    assert probe.path == str(tmp_path)


@pytest.mark.parametrize(
    "which,is_xfs,options,has_cap,can_query,expected",
    [
        (None, True, {"prjquota"}, True, True, "xfs_quota_missing"),
        ("/usr/bin/xfs_quota", False, {"prjquota"}, True, True, "storage_not_xfs"),
        ("/usr/bin/xfs_quota", True, {"rw"}, True, True, "project_quota_not_enabled"),
        ("/usr/bin/xfs_quota", True, {"prjquota"}, False, True, "cap_sys_admin_missing"),
        ("/usr/bin/xfs_quota", True, {"prjquota"}, True, False, "xfs_quota_unusable"),
    ],
)
def test_xfs_probe_reports_conservative_reasons(
    monkeypatch, tmp_path, which, is_xfs, options, has_cap, can_query, expected
):
    service = XfsQuotaService()
    monkeypatch.setattr(settings, "xfs_quota_enabled", True)
    monkeypatch.setattr(settings, "volume_storage_path", str(tmp_path))
    monkeypatch.setattr(xfs_module.shutil, "which", lambda _name: which)
    monkeypatch.setattr(service, "_is_xfs", lambda _path: is_xfs)
    monkeypatch.setattr(service, "_find_mountpoint", lambda _path: str(tmp_path))
    monkeypatch.setattr(service, "_mount_options", lambda _path: options)
    monkeypatch.setattr(xfs_module, "_has_effective_cap_sys_admin", lambda: has_cap)
    monkeypatch.setattr(service, "_xfs_quota_can_query", lambda _path: can_query)

    probe = service.probe_configured_storage()

    assert probe.available is False
    assert probe.reason == expected


def test_xfs_probe_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "xfs_quota_enabled", False)
    probe = XfsQuotaService().probe_configured_storage()
    assert probe.available is False
    assert probe.reason == "xfs_quota_disabled"


def test_xfs_probe_helpers_are_read_only(tmp_path):
    assert xfs_module._unescape_mount("a\\040b\\011c") == "a b\tc"
    assert xfs_module._existing_ancestor(str(tmp_path / "missing" / "child")) == str(tmp_path)
    assert isinstance(xfs_module._has_effective_cap_sys_admin(), bool)
    assert isinstance(XfsQuotaService._mount_options("/"), set)


def test_xfs_quota_query_uses_read_only_state_command(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(xfs_module.subprocess, "run", fake_run)
    assert XfsQuotaService._xfs_quota_can_query("/data") is True
    assert calls[0][0] == ["xfs_quota", "-x", "-c", "state", "/data"]
    assert "limit" not in calls[0][0]
    assert "project" not in calls[0][0]


@pytest.mark.asyncio
async def test_capabilities_report_unenforced_storage_without_blocking_by_default(
    db_session, test_user, monkeypatch
):
    _patch_probe(monkeypatch, _probe(False))

    capabilities = await BatchJobService(db_session).capabilities(test_user)

    assert capabilities.can_submit is True
    assert capabilities.reason_code is None
    assert capabilities.storage_limits_enforced is False
    assert capabilities.storage_enforcement_required is False


@pytest.mark.asyncio
async def test_capabilities_fail_closed_when_enforcement_is_required(
    db_session, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", True)
    _patch_probe(monkeypatch, _probe(False))

    capabilities = await BatchJobService(db_session).capabilities(test_user)

    assert capabilities.enabled is True
    assert capabilities.can_submit is False
    assert capabilities.reason_code == "storage_limits_unenforced"
    assert capabilities.storage_limits_enforced is False
    assert capabilities.storage_enforcement_required is True


@pytest.mark.asyncio
async def test_capabilities_allow_required_and_enforced_storage(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", True)
    _patch_probe(monkeypatch, _probe(True, reason="enforced"))

    capabilities = await BatchJobService(db_session).capabilities(test_user)

    assert capabilities.can_submit is True
    assert capabilities.reason_code is None
    assert capabilities.storage_limits_enforced is True
    assert capabilities.storage_enforcement_required is True


@pytest.mark.asyncio
async def test_submit_fails_closed_without_creating_a_job(db_session, test_user, monkeypatch):
    resources = await _make_resources(db_session, test_user)
    request = BatchJobSubmitRequest(
        name="unenforced",
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=["true"],
        max_runtime_seconds=300,
    )
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", True)
    _patch_probe(monkeypatch, _probe(False))

    with pytest.raises(JobError) as failure:
        await BatchJobService(db_session).submit(test_user, uuid.uuid4().hex, request)

    assert failure.value.code == "storage_limits_unenforced"
    assert failure.value.status_code == 503
    assert (
        await db_session.scalar(
            select(func.count()).select_from(BatchJob).where(BatchJob.user_id == test_user.id)
        )
        == 0
    )

    _patch_probe(monkeypatch, _probe(True, reason="enforced"))
    detail = await BatchJobService(db_session).submit(test_user, uuid.uuid4().hex, request)
    assert detail.state == "queued"


@pytest.mark.asyncio
async def test_submit_keeps_current_behavior_when_enforcement_is_not_required(
    db_session, test_user, monkeypatch
):
    resources = await _make_resources(db_session, test_user)
    request = BatchJobSubmitRequest(
        name="unenforced-default",
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=["true"],
        max_runtime_seconds=300,
    )
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", False)
    _patch_probe(monkeypatch, _probe(False))

    detail = await BatchJobService(db_session).submit(test_user, uuid.uuid4().hex, request)

    assert detail.state == "queued"
    assert detail.billing.mode == "zero_cost"


@pytest.mark.asyncio
async def test_admission_keeps_job_queued_when_required_storage_is_unenforced(
    db_session, test_user, monkeypatch
):
    fixture = await _make_job(db_session, test_user)
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", True)
    _patch_probe(monkeypatch, _probe(False))
    service = BatchJobAdmissionService(db_session, admission_driver())

    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "queued"
    assert job.reason_code == "storage_limits_unenforced"
    assert job.reservation_active is False
    detail = await BatchJobService(db_session).get(test_user, fixture.job_id)
    assert detail.reason_message == "Writable storage limits are not kernel-enforced on this host."

    _patch_probe(monkeypatch, _probe(True, reason="enforced"))
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert admission is not None
    assert admission.job_id == fixture.job_id


def test_storage_capability_probe_returns_sanitized_reason(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", False)
    _patch_probe(monkeypatch, _probe(False, reason="storage_not_xfs"))

    capability = StorageCapabilityService.probe()

    assert capability.enforced is False
    assert capability.required is False
    assert capability.reason_code == "storage_not_xfs"


def test_storage_probe_exception_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", True)
    monkeypatch.setattr(
        xfs_quota_service,
        "probe_configured_storage",
        lambda: (_ for _ in ()).throw(RuntimeError("broken probe")),
    )

    capability = StorageCapabilityService.probe()

    assert capability.enforced is False
    assert capability.required is True
    assert capability.reason_code == "storage_probe_failed"
