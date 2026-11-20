# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.server_launch import NormalizedLaunchRequest
from app.services.server_launch_validation import (
    LaunchValidationError,
    normalize_launch_request,
    validate_launch_volumes,
)

GIB = 1024**3


def input_request(**kwargs):
    return {"name": "science_01", "plan_id": str(uuid4()), "environment_id": str(uuid4()), **kwargs}


def test_default_is_blank_autocreated_home_selection():
    result = normalize_launch_request(input_request(), username="researcher")
    assert result.volume_mounts[0].model_dump() == {
        "volume_id": "",
        "mount_path": "/home/researcher",
        "mode": "read_write",
        "is_primary": True,
        "max_size_bytes": None,
    }
    assert result.model_dump(mode="json")["volume_mounts"][0]["volume_id"] == ""


def test_legacy_read_only_volume_targets_home():
    selection = uuid4()
    request = input_request(volume_id=str(selection), volume_mode="read_only")
    result = normalize_launch_request(request, username="researcher")
    assert result.volume_mounts[0].volume_id == selection
    assert result.volume_mounts[0].mount_path == "/home/researcher"
    assert result.volume_mounts[0].mode == "read_only"


def test_multimount_preserves_intent_and_takes_precedence():
    selection = uuid4()
    result = normalize_launch_request(
        input_request(
            volume_id=str(uuid4()),
            volume_mounts=[
                {"volume_id": "", "mount_path": "/data//./input/", "max_size_bytes": GIB},
                {
                    "volume_id": str(selection),
                    "mount_path": "/results",
                    "mode": "read_only",
                    "is_primary": True,
                },
            ],
        ),
        username="researcher",
    )
    assert result.volume_mounts[0].volume_id == ""
    assert result.volume_mounts[0].mount_path == "/data/input"
    assert result.volume_mounts[0].max_size_bytes == GIB
    assert result.volume_mounts[1].volume_id == selection
    assert result.volume_mounts[1].mode == "read_only"
    assert [mount.is_primary for mount in result.volume_mounts] == [True, False]


@pytest.mark.parametrize(
    "updates",
    [
        {"name": "-invalid"},
        {"name": "x" * 65},
        {"plan_id": "invalid"},
        {"environment_id": "invalid"},
        {"volume_id": "invalid"},
        {"volume_mode": "rw"},
        {"unapproved_env": "TOKEN=secret"},
        {"volume_mounts": [{"volume_id": "", "mode": "rw"}]},
        {"volume_mounts": [{"volume_id": "", "max_size_bytes": 0}]},
        {"volume_mounts": [{"volume_id": "", "max_size_bytes": -1}]},
        {"volume_mounts": [{"volume_id": "", "max_size_bytes": True}]},
        {"volume_mounts": [{"volume_id": "", "max_size_bytes": "1024"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "/"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "/data/../etc"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "relative"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "/data\x00evil"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "/data\\evil"}]},
        {"volume_mounts": [{"volume_id": "", "mount_path": "/x"}] * 33},
        {
            "volume_mounts": [
                {"volume_id": "", "mount_path": "/x"},
                {"volume_id": "", "mount_path": "/x/"},
            ]
        },
    ],
)
def test_invalid_launch_intent_rejected(updates):
    with pytest.raises(ValidationError):
        normalize_launch_request(input_request(**updates), username="researcher")


def test_duplicate_volume_selection_rejected():
    selection = str(uuid4())
    with pytest.raises(ValidationError, match="selected once"):
        normalize_launch_request(
            input_request(
                volume_mounts=[
                    {"volume_id": selection, "mount_path": "/x"},
                    {"volume_id": selection, "mount_path": "/y"},
                ]
            ),
            username="researcher",
        )


def test_username_cannot_inject_default_mount():
    with pytest.raises(LaunchValidationError, match="invalid_username"):
        normalize_launch_request(input_request(), username="../other")


def test_normalized_primary_must_be_first_only():
    source = normalize_launch_request(input_request(), username="researcher").model_dump()
    source["volume_mounts"][0]["is_primary"] = False
    with pytest.raises(ValidationError, match="only primary"):
        NormalizedLaunchRequest.model_validate(source)


def policy_fixture(*, mounts=None, volumes=None, allowed=True):
    request = normalize_launch_request(input_request(volume_mounts=mounts), username="researcher")
    plan = SimpleNamespace(id=request.plan_id, disk_limit="10g")
    user = SimpleNamespace(id=uuid4(), username="researcher")
    result = MagicMock()
    result.scalars.return_value.all.return_value = volumes or []
    db = MagicMock(execute=AsyncMock(return_value=result), commit=AsyncMock(), flush=AsyncMock())
    access = AsyncMock(return_value=allowed)
    quota = AsyncMock(return_value={"allowed": True})
    return request, plan, user, db, access, quota


@pytest.mark.asyncio
async def test_default_capacity_filled_without_allocating_or_committing():
    request, plan, user, db, access, quota = policy_fixture()
    with (
        patch(
            "app.services.server_launch_validation.VolumeAccessService.can_access_volume", access
        ),
        patch(
            "app.services.server_launch_validation.QuotaService.check_volume_creation_allowed",
            quota,
        ),
    ):
        result = await validate_launch_volumes(db, user, request, plan)
    assert result[0].volume_id == ""
    assert result[0].max_size_bytes == 10 * GIB
    quota.assert_awaited_once_with(
        user_id=str(user.id), requested_size_bytes=10 * GIB, commit=False
    )
    db.execute.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    access.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_auto_sizes_checked_as_one_quota_total():
    request, plan, user, db, access, quota = policy_fixture(
        mounts=[
            {"volume_id": "", "mount_path": "/x", "max_size_bytes": 2 * GIB},
            {"volume_id": "", "mount_path": "/y", "max_size_bytes": 3 * GIB},
        ]
    )
    with patch(
        "app.services.server_launch_validation.QuotaService.check_volume_creation_allowed", quota
    ):
        result = await validate_launch_volumes(db, user, request, plan)
    assert [mount.volume_id for mount in result] == ["", ""]
    quota.assert_awaited_once_with(user_id=str(user.id), requested_size_bytes=5 * GIB, commit=False)


@pytest.mark.asyncio
async def test_existing_read_only_access_and_aggregate_capacity():
    selection = uuid4()
    volume = SimpleNamespace(id=selection, status="active", size_bytes=GIB, max_size_bytes=3 * GIB)
    request, plan, user, db, access, quota = policy_fixture(
        mounts=[
            {"volume_id": str(selection), "mount_path": "/existing", "mode": "read_only"},
            {"volume_id": "", "mount_path": "/new", "max_size_bytes": 2 * GIB},
        ],
        volumes=[volume],
    )
    with (
        patch(
            "app.services.server_launch_validation.VolumeAccessService.can_access_volume", access
        ),
        patch(
            "app.services.server_launch_validation.QuotaService.check_volume_creation_allowed",
            quota,
        ),
    ):
        result = await validate_launch_volumes(db, user, request, plan)
    assert result[0].volume_id == selection
    access.assert_awaited_once_with(str(selection), str(user.id), "read_only")
    assert db.execute.call_args.args[0].get_execution_options()["populate_existing"]
    quota.assert_awaited_once_with(user_id=str(user.id), requested_size_bytes=2 * GIB, commit=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "volume_status,accessible,code",
    [
        ("active", False, "volume_unavailable"),
        ("archived", True, "volume_unavailable"),
        ("deleting", True, "volume_unavailable"),
        ("restoring", True, "volume_unavailable"),
    ],
)
async def test_unavailable_volume_cannot_be_queued(volume_status, accessible, code):
    selection = uuid4()
    volume = SimpleNamespace(id=selection, status=volume_status, size_bytes=0, max_size_bytes=GIB)
    request, plan, user, db, access, quota = policy_fixture(
        mounts=[
            {"volume_id": str(selection), "mount_path": "/data"},
        ],
        volumes=[volume],
        allowed=accessible,
    )
    with patch(
        "app.services.server_launch_validation.VolumeAccessService.can_access_volume", access
    ):
        with pytest.raises(LaunchValidationError, match=code):
            await validate_launch_volumes(db, user, request, plan)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_volume_does_not_disclose_metadata():
    request, plan, user, db, access, quota = policy_fixture(
        mounts=[
            {"volume_id": str(uuid4()), "mount_path": "/data"},
        ]
    )
    with pytest.raises(LaunchValidationError, match="volume_unavailable"):
        await validate_launch_volumes(db, user, request, plan)


@pytest.mark.asyncio
@pytest.mark.parametrize("size,new_size", [(11 * GIB, None), (8 * GIB, 3 * GIB)])
async def test_per_volume_and_combined_existing_new_capacity(size, new_size):
    selection = uuid4()
    volume = SimpleNamespace(id=selection, status="active", size_bytes=0, max_size_bytes=size)
    mounts = [{"volume_id": str(selection), "mount_path": "/existing"}]
    if new_size:
        mounts.append({"volume_id": "", "mount_path": "/new", "max_size_bytes": new_size})
    request, plan, user, db, access, quota = policy_fixture(mounts=mounts, volumes=[volume])
    with patch(
        "app.services.server_launch_validation.VolumeAccessService.can_access_volume", access
    ):
        with pytest.raises(LaunchValidationError, match="volume_capacity_exceeded"):
            await validate_launch_volumes(db, user, request, plan)


@pytest.mark.asyncio
async def test_requested_auto_capacity_cannot_exceed_plan():
    request, plan, user, db, access, quota = policy_fixture(
        mounts=[
            {"volume_id": "", "max_size_bytes": 11 * GIB},
        ]
    )
    with pytest.raises(LaunchValidationError, match="volume_capacity_exceeded"):
        await validate_launch_volumes(db, user, request, plan)


@pytest.mark.asyncio
async def test_quota_denial_is_sanitized_and_no_commit_occurs():
    request, plan, user, db, access, quota = policy_fixture()
    quota.return_value = {"allowed": False, "reason": "private storage metadata"}
    with patch(
        "app.services.server_launch_validation.QuotaService.check_volume_creation_allowed", quota
    ):
        with pytest.raises(LaunchValidationError, match="^quota_exceeded$") as caught:
            await validate_launch_volumes(db, user, request, plan)
    assert caught.value.status_code == 429
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_mismatch_rejected_before_policy_io():
    request, plan, user, db, access, quota = policy_fixture()
    plan.id = uuid4()
    with pytest.raises(LaunchValidationError, match="configuration_changed"):
        await validate_launch_volumes(db, user, request, plan)
    db.execute.assert_not_awaited()


def test_runtime_home_alias_frozen_to_actual_user_home(monkeypatch):
    monkeypatch.setattr("app.services.server_launch_validation.settings.container_user", "nukelab")
    result = normalize_launch_request(
        input_request(
            volume_mounts=[
                {"volume_id": "", "mount_path": "/home/nukelab/"},
            ]
        ),
        username="researcher",
    )
    assert result.volume_mounts[0].mount_path == "/home/researcher"


def test_home_alias_collision_rejected_after_normalization(monkeypatch):
    monkeypatch.setattr("app.services.server_launch_validation.settings.container_user", "nukelab")
    with pytest.raises(ValidationError, match="distinct"):
        normalize_launch_request(
            input_request(
                volume_mounts=[
                    {"volume_id": "", "mount_path": "/home/nukelab"},
                    {"volume_id": "", "mount_path": "/home/researcher"},
                ]
            ),
            username="researcher",
        )
