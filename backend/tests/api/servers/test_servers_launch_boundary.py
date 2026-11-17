# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Real HTTP, policy and persistence contracts with an isolated runtime boundary."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.models.credit_transaction import CreditTransaction
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation


@dataclass(frozen=True)
class LaunchAPI:
    owner_id: uuid.UUID
    plan_id: uuid.UUID
    environment_id: uuid.UUID
    username: str

    def body(self, name="experiment"):
        return {
            "name": name,
            "plan_id": str(self.plan_id),
            "environment_id": str(self.environment_id),
            "volume_mounts": [
                {
                    "volume_id": "",
                    "mount_path": f"/home/{self.username}",
                    "mode": "read_write",
                    "max_size_bytes": 1024**3,
                }
            ],
        }


@pytest_asyncio.fixture
async def launch_api(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "credits_enabled", True)
    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    monkeypatch.setattr(settings, "gpu_devices", "")
    monkeypatch.setattr(settings, "xfs_quota_enabled", False)
    test_user.nuke_balance = 100
    plan = ServerPlan(
        name="HTTP plan",
        slug="http-plan",
        cpu_limit=1,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        is_active=True,
        is_public=True,
        cost_per_hour=3,
        max_servers_per_user=5,
    )
    environment = EnvironmentTemplate(
        name="HTTP environment",
        slug="http-environment",
        image="approved:latest",
        is_active=True,
        is_public=True,
    )
    quota = await db_session.scalar(
        select(ResourceQuota).where(ResourceQuota.user_id == test_user.id)
    )
    if quota is None:
        quota = ResourceQuota(user_id=test_user.id)
        db_session.add(quota)
    (
        quota.max_cpu_total,
        quota.max_memory_total,
        quota.max_disk_total,
        quota.max_gpu_total,
        quota.max_servers_total,
    ) = 10, "16g", "30g", 4, 10
    db_session.add_all([plan, environment])
    await db_session.flush()
    data = LaunchAPI(test_user.id, plan.id, environment.id, test_user.username)
    await db_session.commit()
    return data


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_immediate_http_launch_has_one_identity_generation_and_no_initial_debit(
    client, user_token, db_session, launch_api, server_api_runtime
):
    response = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert response.status_code == 200, response.text
    body = response.json()
    server_id = uuid.UUID(body["id"])
    server = await db_session.get(Server, server_id)
    assert body["status"] == "running" and server.image.startswith("sha256:")
    assert body["container_id"] == server.container_id
    assert (await db_session.scalar(select(func.count()).select_from(Server))) == 1
    assert (await db_session.get(ServerLaunchOperation, server_id)).state == "succeeded"
    assert (await db_session.get(ServerLaunchRecord, server_id)).generation == 1
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0
    assert (await db_session.get(User, launch_api.owner_id)).nuke_balance == 100
    assert server.started_at == server.last_billed_at
    assert server_api_runtime.create_container.await_count == 1


@pytest.mark.asyncio
async def test_queue_http_acceptance_preserves_blank_mount_and_reserves_no_volume_or_credit(
    client, user_token, db_session, launch_api, server_api_runtime, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    submitted = launch_api.body("waiting")
    response = await client.post("/api/servers/", headers=auth(user_token), json=submitted)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["queued"] is True and body["queue_position"] == 1
    assert (
        body["request"]["name"] == "waiting" and body["request"]["resources"]["memory_mib"] == 1024
    )
    entry = await db_session.get(ServerQueue, uuid.UUID(body["queue_id"]))
    assert entry.request_version == 1 and entry.revision_id is not None
    assert entry.request_payload["volume_mounts"][0] == submitted["volume_mounts"][0] | {
        "is_primary": True
    }
    assert entry.plan_snapshot["cost_per_hour"] == 3
    for model in (Server, Volume, GpuAllocation, CreditTransaction):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    server_api_runtime.create_container.assert_not_awaited()
    server_api_runtime.ensure_volume.assert_not_awaited()
    schema = (await client.get("/api/openapi.json")).json()
    assert "202" in schema["paths"]["/servers/"]["post"]["responses"]


@pytest.mark.asyncio
async def test_queue_list_detail_cancel_are_owned_and_cancel_is_idempotent(
    client, user_token, admin_token, db_session, launch_api, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    accepted = (
        await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    ).json()
    queue_id = accepted["queue_id"]
    assert (
        await client.get("/api/server-queue/capabilities", headers=auth(user_token))
    ).json() == {"enabled": True}
    page = await client.get("/api/server-queue", headers=auth(user_token))
    assert page.status_code == 200 and page.json()["total"] == 1
    assert (
        await client.get(f"/api/server-queue/{queue_id}", headers=auth(admin_token))
    ).status_code == 404
    assert (
        await client.post(f"/api/server-queue/{queue_id}/cancel", headers=auth(admin_token))
    ).status_code == 404
    for _ in range(2):
        cancelled = await client.post(
            f"/api/server-queue/{queue_id}/cancel", headers=auth(user_token)
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled" and cancelled.json()["position"] is None
        assert cancelled.json()["can_cancel"] is False
    assert "request_payload" not in page.text and "gpu_devices" not in page.text


@pytest.mark.asyncio
async def test_pending_retry_points_to_same_request_and_bounds_are_enforced(
    client, user_token, db_session, launch_api, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    monkeypatch.setattr(settings, "queue_max_pending_per_owner", 1)
    first = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    duplicate = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {
        "code": "request_already_exists",
        "queue_id": first.json()["queue_id"],
    }
    overflow = await client.post(
        "/api/servers/", headers=auth(user_token), json=launch_api.body("another")
    )
    assert (
        overflow.status_code == 429 and overflow.json()["detail"]["code"] == "queue_limit_exceeded"
    )
    assert await db_session.scalar(select(func.count()).select_from(ServerQueue)) == 1


@pytest.mark.parametrize(
    "failure,expected,code",
    [
        ("credits", 402, "insufficient_credits"),
        ("quota", 429, "quota_exceeded"),
        ("environment", 403, "permission_revoked"),
        ("foreign_volume", 403, "volume_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_current_policy_rejection_has_no_compute_or_data_side_effect(
    client, user_token, db_session, launch_api, server_api_runtime, failure, expected, code
):
    body = launch_api.body()
    if failure == "credits":
        (await db_session.get(User, launch_api.owner_id)).nuke_balance = 0
    elif failure == "quota":
        quota = await db_session.scalar(
            select(ResourceQuota).where(ResourceQuota.user_id == launch_api.owner_id)
        )
        quota.max_cpu_total = 0
    elif failure == "environment":
        (await db_session.get(EnvironmentTemplate, launch_api.environment_id)).is_public = False
    else:
        body["volume_mounts"][0]["volume_id"] = str(uuid.uuid4())
    await db_session.commit()
    response = await client.post("/api/servers/", headers=auth(user_token), json=body)
    assert response.status_code == expected, response.text
    assert response.json()["detail"]["code"] == code
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 0
    server_api_runtime.create_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhausted_exclusive_gpu_pool_returns_waiting_acceptance(
    client, user_token, db_session, launch_api, monkeypatch
):
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    (await db_session.get(ServerPlan, launch_api.plan_id)).gpu_limit = 1
    occupied = Server(
        name="occupied", user_id=launch_api.owner_id, status="running", allocated_gpu=1
    )
    db_session.add(occupied)
    await db_session.flush()
    db_session.add(GpuAllocation(server_id=occupied.id, device="nvidia.com/gpu=0"))
    await db_session.commit()
    response = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert response.status_code == 202, response.text
    entry = await db_session.get(ServerQueue, uuid.UUID(response.json()["queue_id"]))
    assert entry.reason_code == "gpu_wait" and entry.requested_gpu == 1


@pytest.mark.parametrize("stage", ["create", "readiness"])
@pytest.mark.asyncio
async def test_unknown_runtime_outcome_retains_claim_and_blocks_stop_delete(
    client, user_token, db_session, launch_api, server_api_runtime, stage
):
    if stage == "create":
        server_api_runtime.create_container.side_effect = RuntimeError("private daemon path")
    else:
        server_api_runtime.wait_for_container_ready.return_value = False
    failed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "recovery_required"
    assert "private daemon" not in failed.text
    server = await db_session.scalar(select(Server).where(Server.name == "experiment"))
    sid = str(server.id)
    assert server.status == "starting"
    assert (await db_session.get(ServerLaunchOperation, server.id)).state == "uncertain"
    assert await db_session.scalar(select(func.count()).select_from(VolumeOperation)) == 1
    for action in ("stop", "restart"):
        rejected = await client.post(f"/api/servers/{sid}/{action}", headers=auth(user_token))
        assert rejected.status_code == 409
    assert (await client.delete(f"/api/servers/{sid}", headers=auth(user_token))).status_code == 409
    server_api_runtime.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_replay_and_stop_replay_do_not_spawn_or_advance_billing_clock(
    client, user_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    sid = deployed.json()["id"]
    assert (
        await client.post(f"/api/servers/{sid}/start", headers=auth(user_token))
    ).status_code == 200
    assert server_api_runtime.create_container.await_count == 1
    assert (
        await client.post(f"/api/servers/{sid}/stop", headers=auth(user_token))
    ).status_code == 200
    server = await db_session.get(Server, uuid.UUID(sid))
    stopped_at, cost = server.stopped_at, server.total_cost
    assert (
        await client.post(f"/api/servers/{sid}/stop", headers=auth(user_token))
    ).status_code == 200
    await db_session.refresh(server)
    assert server.stopped_at == stopped_at and server.total_cost == cost
    assert not (
        await db_session.scalars(
            select(VolumeOperation).where(
                VolumeOperation.state.in_(["reserved", "running", "recovery_required"])
            )
        )
    ).all()


@pytest.mark.asyncio
async def test_restart_and_running_rename_use_new_generations_with_the_captured_image(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    sid = deployed.json()["id"]
    first_image = server_api_runtime.create_container.call_args.kwargs["image"]
    (await db_session.get(EnvironmentTemplate, launch_api.environment_id)).image = "new:tag"
    await db_session.commit()
    restarted = await client.post(f"/api/servers/{sid}/restart", headers=auth(user_token))
    assert restarted.status_code == 200, restarted.text
    renamed = await client.patch(
        f"/api/servers/{sid}",
        headers=auth(admin_token),
        json={"name": "renamed", "reason": "Owner requested rename"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed"
    assert server_api_runtime.create_container.call_args.kwargs["image"] == first_image
    records = (
        await db_session.scalars(
            select(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == uuid.UUID(sid))
            .order_by(ServerLaunchRecord.generation)
        )
    ).all()
    assert [record.generation for record in records] == [1, 2, 3]


@pytest.mark.asyncio
async def test_stopped_edit_does_not_start_runtime_and_legacy_offline_name_is_supported(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    sid = deployed.json()["id"]
    await client.post(f"/api/servers/{sid}/stop", headers=auth(user_token))
    count = server_api_runtime.create_container.await_count
    changed = await client.patch(
        f"/api/servers/{sid}",
        headers=auth(admin_token),
        json={"name": "offline-renamed", "reason": "Rename offline server"},
    )
    assert changed.status_code == 200, changed.text
    assert (
        changed.json()["status"] == "stopped"
        and server_api_runtime.create_container.await_count == count
    )
    legacy = Server(name="legacy-name", user_id=launch_api.owner_id, status="stopped")
    db_session.add(legacy)
    await db_session.commit()
    changed = await client.patch(
        f"/api/servers/{legacy.id}",
        headers=auth(admin_token),
        json={"name": "legacy-renamed", "reason": "Rename offline legacy server"},
    )
    assert changed.status_code == 200


@pytest.mark.asyncio
async def test_offline_auto_volume_initialization_is_consumed_by_successful_start(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    sid = deployed.json()["id"]
    assert (
        await client.post(f"/api/servers/{sid}/stop", headers=auth(user_token))
    ).status_code == 200
    edited = await client.patch(
        f"/api/servers/{sid}",
        headers=auth(admin_token),
        json={
            "volume_mounts": launch_api.body()["volume_mounts"],
            "reason": "Replace offline data selection",
        },
    )
    assert edited.status_code == 200, edited.text
    pending = await db_session.scalar(
        select(Volume).where(Volume.labels["initialize_for_server"].astext == sid)
    )
    assert pending is not None
    volume_id = pending.id
    started = await client.post(f"/api/servers/{sid}/start", headers=auth(user_token))
    assert started.status_code == 200, started.text
    await db_session.refresh(pending)
    assert "initialize_for_server" not in pending.labels
    assert (
        await db_session.scalar(
            select(ServerVolume.volume_id).where(ServerVolume.server_id == uuid.UUID(sid))
        )
        == volume_id
    )


@pytest.mark.parametrize("action", ["start", "restart", "update"])
@pytest.mark.parametrize(
    "failure,expected,code",
    [
        ("plan_access", 403, "permission_revoked"),
        ("inactive_plan", 409, "configuration_changed"),
        ("credits", 402, "insufficient_credits"),
        ("quota", 429, "quota_exceeded"),
        ("volume_capacity", 400, "volume_capacity_exceeded"),
    ],
)
@pytest.mark.asyncio
async def test_existing_actions_recheck_policy_before_runtime_or_new_reservations(
    client,
    user_token,
    admin_token,
    db_session,
    launch_api,
    server_api_runtime,
    action,
    failure,
    expected,
    code,
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert deployed.status_code == 200, deployed.text
    server_id = uuid.UUID(deployed.json()["id"])
    if action == "start":
        assert (
            await client.post(f"/api/servers/{server_id}/stop", headers=auth(user_token))
        ).status_code == 200
    if failure == "plan_access":
        plan = await db_session.get(ServerPlan, launch_api.plan_id)
        plan.is_public, plan.visible_to_roles = False, []
    elif failure == "inactive_plan":
        (await db_session.get(ServerPlan, launch_api.plan_id)).is_active = False
    elif failure == "credits":
        (await db_session.get(User, launch_api.owner_id)).nuke_balance = 0
    elif failure == "quota":
        quota = await db_session.scalar(
            select(ResourceQuota).where(ResourceQuota.user_id == launch_api.owner_id)
        )
        quota.max_cpu_total = 0
    else:
        volume_id = await db_session.scalar(
            select(ServerVolume.volume_id).where(ServerVolume.server_id == server_id)
        )
        (await db_session.get(Volume, volume_id)).max_size_bytes = 3 * 1024**3
    await db_session.commit()
    previous = await db_session.get(Server, server_id)
    before = (previous.status, previous.name, previous.container_id)
    counts = [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Volume, ServerLaunchOperation, VolumeOperation, ServerLaunchRecord)
    ]
    calls = (
        server_api_runtime.create_container.await_count,
        server_api_runtime.stop_container.await_count,
        server_api_runtime.delete_container.await_count,
    )
    if action == "update":
        response = await client.patch(
            f"/api/servers/{server_id}",
            headers=auth(admin_token),
            json={"name": "denied-change", "reason": "Policy regression"},
        )
    else:
        response = await client.post(f"/api/servers/{server_id}/{action}", headers=auth(user_token))
    if failure == "inactive_plan" and action in ("start", "restart"):
        expected, code = 403, "permission_revoked"
    assert response.status_code == expected, response.text
    assert response.json()["detail"]["code"] == code
    await db_session.refresh(previous)
    assert (previous.status, previous.name, previous.container_id) == before
    assert [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Volume, ServerLaunchOperation, VolumeOperation, ServerLaunchRecord)
    ] == counts
    assert (
        server_api_runtime.create_container.await_count,
        server_api_runtime.stop_container.await_count,
        server_api_runtime.delete_container.await_count,
    ) == calls


@pytest.mark.asyncio
async def test_update_rejects_aggregate_capacity_and_foreign_mount_without_mutation(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    server_id = uuid.UUID(deployed.json()["id"])
    original_volume = uuid.UUID(deployed.json()["volume_mounts"][0]["volume_id"])
    volumes = [
        Volume(
            name=f"capacity-{i}",
            display_name="Capacity",
            owner_id=launch_api.owner_id,
            visibility="private",
            status="active",
            size_bytes=0,
            max_size_bytes=1536 * 1024**2,
        )
        for i in range(2)
    ]
    db_session.add_all(volumes)
    await db_session.commit()
    mounts = [
        {"volume_id": str(volume.id), "mount_path": f"/data/{i}", "mode": "read_write"}
        for i, volume in enumerate(volumes)
    ]
    response = await client.patch(
        f"/api/servers/{server_id}",
        headers=auth(admin_token),
        json={"volume_mounts": mounts, "reason": "Aggregate capacity check"},
    )
    assert (
        response.status_code == 400
        and response.json()["detail"]["code"] == "volume_capacity_exceeded"
    )
    response = await client.patch(
        f"/api/servers/{server_id}",
        headers=auth(admin_token),
        json={
            "volume_mounts": [
                {"volume_id": str(uuid.uuid4()), "mount_path": "/data", "mode": "read_write"}
            ],
            "reason": "Volume access check",
        },
    )
    assert response.status_code == 403 and response.json()["detail"]["code"] == "volume_unavailable"
    assert (
        await db_session.scalar(
            select(ServerVolume.volume_id).where(ServerVolume.server_id == server_id)
        )
        == original_volume
    )
    assert server_api_runtime.create_container.await_count == 1
    server_api_runtime.stop_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_display_name_is_allowed_for_another_owner(
    client, user_token, admin_user, db_session, launch_api
):
    db_session.add(Server(name="shared-display", user_id=admin_user.id, status="stopped"))
    await db_session.commit()
    result = await client.post(
        "/api/servers/", headers=auth(user_token), json=launch_api.body("shared-display")
    )
    assert result.status_code == 200, result.text
    rows = list(await db_session.scalars(select(Server).where(Server.name == "shared-display")))
    assert len(rows) == 2 and len({row.user_id for row in rows}) == 2


@pytest.mark.asyncio
async def test_gpu_stop_start_and_restart_recreate_with_reserved_devices(
    client, user_token, db_session, launch_api, server_api_runtime, monkeypatch
):
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    (await db_session.get(ServerPlan, launch_api.plan_id)).gpu_limit = 1
    await db_session.commit()
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert deployed.status_code == 200, deployed.text
    server_id = uuid.UUID(deployed.json()["id"])
    first_image = server_api_runtime.create_container.call_args.kwargs["image"]
    assert (
        await client.post(f"/api/servers/{server_id}/stop", headers=auth(user_token))
    ).status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 0
    assert (
        await client.post(f"/api/servers/{server_id}/start", headers=auth(user_token))
    ).status_code == 200
    assert (
        await client.post(f"/api/servers/{server_id}/restart", headers=auth(user_token))
    ).status_code == 200
    assert server_api_runtime.create_container.await_count == 3
    for call in server_api_runtime.create_container.await_args_list:
        assert (
            call.kwargs["gpu_devices"] == ["nvidia.com/gpu=0"]
            and call.kwargs["image"] == first_image
        )
    allocation = await db_session.scalar(select(GpuAllocation))
    assert allocation.server_id == server_id and allocation.device == "nvidia.com/gpu=0"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == server_id)
        )
        == 3
    )


@pytest.mark.asyncio
async def test_stop_reconciles_actual_usage_and_quota_once(
    client, user_token, db_session, launch_api
):
    from datetime import timedelta

    from app.core.time_utils import utc_now

    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    server_id = uuid.UUID(deployed.json()["id"])
    server = await db_session.get(Server, server_id)
    server.started_at = utc_now() - timedelta(hours=1)
    await db_session.commit()
    stopped = await client.post(f"/api/servers/{server_id}/stop", headers=auth(user_token))
    assert stopped.status_code == 200, stopped.text
    await db_session.refresh(server)
    owner = await db_session.get(User, launch_api.owner_id, populate_existing=True)
    quota = await db_session.scalar(
        select(ResourceQuota).where(ResourceQuota.user_id == launch_api.owner_id)
    )
    assert server.total_cost == 3 and owner.nuke_balance == 97
    assert quota.usage_servers == 0 and quota.usage_cpu == 0
    transactions = list(
        await db_session.scalars(
            select(CreditTransaction).where(CreditTransaction.server_id == server_id)
        )
    )
    assert len(transactions) == 1 and transactions[0].amount == -3
    await client.post(f"/api/servers/{server_id}/stop", headers=auth(user_token))
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.server_id == server_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_explicit_plan_and_environment_edit_records_new_identity(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    server_id = uuid.UUID(deployed.json()["id"])
    original_image = server_api_runtime.create_container.call_args.kwargs["image"]
    plan = ServerPlan(
        name="Larger current plan",
        slug="larger-current",
        cpu_limit=2,
        memory_limit="4g",
        disk_limit="6g",
        gpu_limit=0,
        cost_per_hour=3,
        max_servers_per_user=5,
        is_public=True,
        is_active=True,
    )
    environment = EnvironmentTemplate(
        name="New approved selection",
        slug="new-approved",
        image="approved:new",
        is_public=True,
        is_active=True,
    )
    db_session.add_all([plan, environment])
    await db_session.commit()
    plan_id, environment_id = plan.id, environment.id
    changed = await client.patch(
        f"/api/servers/{server_id}",
        headers=auth(admin_token),
        json={
            "plan_id": str(plan_id),
            "environment_id": str(environment_id),
            "reason": "Approved selection change",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["allocated_cpu"] == 2 and changed.json()["allocated_memory"] == "4g"
    assert changed.json()["environment_id"] == str(environment_id)
    selected_image = server_api_runtime.create_container.call_args.kwargs["image"]
    assert selected_image != original_image
    records = list(
        await db_session.scalars(
            select(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == server_id)
            .order_by(ServerLaunchRecord.generation)
        )
    )
    assert [row.generation for row in records] == [1, 2] and records[0].revision_id != records[
        1
    ].revision_id


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["restart", "update"])
async def test_replacement_failure_retains_current_reservation_and_original_history(
    client, user_token, admin_token, db_session, launch_api, server_api_runtime, action
):
    deployed = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    server_id = uuid.UUID(deployed.json()["id"])
    server_api_runtime.create_container.side_effect = RuntimeError("private daemon failure")
    if action == "update":
        response = await client.patch(
            f"/api/servers/{server_id}",
            headers=auth(admin_token),
            json={"name": "replacement", "reason": "Replacement failure check"},
        )
    else:
        response = await client.post(f"/api/servers/{server_id}/restart", headers=auth(user_token))
    assert response.status_code == 503, response.text
    assert (
        response.json()["detail"]["code"] == "recovery_required"
        and "private daemon" not in response.text
    )
    server = await db_session.get(Server, server_id, populate_existing=True)
    assert server.status == "starting" and server.allocated_cpu == 1
    operations = list(
        await db_session.scalars(
            select(ServerLaunchOperation).where(
                ServerLaunchOperation.server_id == server_id,
                ServerLaunchOperation.state == "uncertain",
            )
        )
    )
    assert len(operations) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == server_id)
        )
        == 1
    )
    assert (
        await client.delete(f"/api/servers/{server_id}", headers=auth(user_token))
    ).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("preference", ["missing", "invalid", "custom", "disabled"])
async def test_launch_expiry_preferences_are_shared_by_direct_and_queued_creation(
    client, user_token, db_session, launch_api, server_api_runtime, monkeypatch, queued, preference
):
    from app.services.server_queue_dispatch_service import ServerQueueDispatchService

    preferences = {
        "missing": {},
        "invalid": {"max_server_runtime": "invalid"},
        "custom": {"max_server_runtime": 7},
        "disabled": {"max_server_runtime_enabled": False},
    }[preference]
    (await db_session.get(User, launch_api.owner_id)).preferences = preferences
    await db_session.commit()
    if queued:
        monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    response = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert response.status_code == (202 if queued else 200), response.text
    if queued:
        monkeypatch.setattr(settings, "resource_pool_cpu", 34)
        result = await ServerQueueDispatchService(db_session, server_api_runtime).dispatch()
        assert result.started == 1
        entry = await db_session.get(ServerQueue, uuid.UUID(response.json()["queue_id"]))
        server_id = entry.server_id
    else:
        server_id = uuid.UUID(response.json()["id"])
    server = await db_session.get(Server, server_id, populate_existing=True)
    if preference == "disabled":
        assert server.expires_at is None
    else:
        seconds = 420 if preference == "custom" else settings.server_max_runtime
        assert abs((server.expires_at - server.started_at).total_seconds() - seconds) < 2
    owner = await db_session.get(User, launch_api.owner_id, populate_existing=True)
    assert owner.nuke_balance == 100
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0
