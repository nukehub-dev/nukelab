# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""HTTP bulk lifecycle delegation, authorization, and session rollback survival."""

import secrets
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import inspect, select

from app.api.auth import get_password_hash
from app.models.activity_log import ActivityLog
from app.models.api_token import ApiToken
from app.models.server import Server
from app.services.server_launch_service import LaunchError

ENDPOINTS = ("/api/admin/servers/bulk-action", "/api/bulk/servers/bulk-action")


async def server_rows(db, owner_id, *, status="stopped", count=1):
    rows = [
        Server(
            id=uuid.uuid4(), user_id=owner_id, name="bulk-" + uuid.uuid4().hex[:10], status=status
        )
        for _ in range(count)
    ]
    db.add_all(rows)
    await db.commit()
    return [row.id for row in rows]


def successes(endpoint, data):
    return data["results"]["success"] if "/admin/" in endpoint else data["succeeded"]


def failures(endpoint, data):
    return data["results"]["failed"] if "/admin/" in endpoint else data["failed"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("action", ["start", "stop", "delete"])
@pytest.mark.asyncio
async def test_http_bulk_actions_use_shared_business_services(
    client, db_session, admin_user, admin_token, endpoint, action
):
    server_id = (
        await server_rows(
            db_session, admin_user.id, status="running" if action == "stop" else "stopped"
        )
    )[0]
    service_name = "ServerLifecycleService" if action == "start" else "ServerTerminationService"
    result = SimpleNamespace(status="running" if action == "start" else "stopped", plan_id=None)
    with (
        patch("app.api.servers." + service_name) as service,
        patch("app.api.servers.get_driver", new_callable=AsyncMock),
        patch("app.api.servers.NotificationService", return_value=AsyncMock()),
        patch("app.api.servers.broadcast_server_status_change", new_callable=AsyncMock),
        patch("app.api.servers._invalidate_server_list_cache", new_callable=AsyncMock),
    ):
        method = AsyncMock(return_value=result)
        setattr(service.return_value, action, method)
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": action, "server_ids": [str(server_id)]},
        )
    assert response.status_code == 200
    assert successes(endpoint, response.json()) == [str(server_id)]
    assert failures(endpoint, response.json()) == []
    method.assert_awaited_once_with(server_id)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.asyncio
async def test_bulk_next_item_survives_service_rollback_expiring_actor_and_server(
    client, db_session, admin_user, admin_token, endpoint
):
    ids = await server_rows(db_session, admin_user.id, count=2)
    calls, expired_actor = [], []

    async def start(server_id):
        calls.append(server_id)
        # Real shared orchestration rolls back a dependency's read transaction.
        await db_session.rollback()
        expired_actor.append(inspect(admin_user).expired)
        if server_id == ids[0]:
            raise LaunchError("launch_in_progress", 409)
        row = await db_session.get(Server, server_id, populate_existing=True)
        row.status = "running"
        await db_session.commit()
        return row

    with (
        patch("app.api.servers.ServerLifecycleService") as lifecycle,
        patch("app.api.servers.get_driver", new_callable=AsyncMock),
        patch("app.api.servers.NotificationService", return_value=AsyncMock()),
        patch("app.api.servers.broadcast_server_status_change", new_callable=AsyncMock),
        patch("app.api.servers._invalidate_server_list_cache", new_callable=AsyncMock),
    ):
        lifecycle.return_value.start = AsyncMock(side_effect=start)
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "start", "server_ids": [str(value) for value in ids]},
        )
    assert response.status_code == 200
    assert calls == ids and expired_actor == [True, True]
    assert successes(endpoint, response.json()) == [str(ids[1])]
    assert failures(endpoint, response.json()) == [
        {"server_id": str(ids[0]), "error": "launch_in_progress"}
    ]
    assert (await db_session.get(Server, ids[1])).status == "running"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.asyncio
async def test_server_bulk_mutations_reject_api_tokens_even_with_manage_scope(
    client, db_session, admin_user, endpoint
):
    raw = "nukelab_" + secrets.token_urlsafe(32)
    db_session.add(
        ApiToken(
            user_id=admin_user.id,
            name="Manage token",
            token_hash=get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["servers:read", "servers:manage"],
            is_active=True,
        )
    )
    await db_session.commit()
    with patch("app.api.servers.ServerLifecycleService") as service:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {raw}"},
            json={"action": "start", "server_ids": []},
        )
    assert response.status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.asyncio
async def test_unknown_uuid_remains_a_per_item_failure(client, admin_token, endpoint):
    missing = str(uuid.uuid4())
    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"action": "start", "server_ids": [missing]},
    )
    assert response.status_code == 200
    assert failures(endpoint, response.json()) == [
        {"server_id": missing, "error": "Server not found"}
    ]


@pytest.mark.asyncio
async def test_bulk_cross_owner_action_retains_reason_and_audit(
    client, db_session, test_user, superadmin_user, superadmin_token
):
    actor_id = superadmin_user.id
    server_id = (await server_rows(db_session, test_user.id))[0]
    with (
        patch("app.api.servers.ServerLifecycleService") as lifecycle,
        patch("app.api.servers.get_driver", new_callable=AsyncMock),
        patch("app.api.servers.NotificationService", return_value=AsyncMock()),
        patch("app.api.servers.broadcast_server_status_change", new_callable=AsyncMock),
        patch("app.api.servers._invalidate_server_list_cache", new_callable=AsyncMock),
    ):
        lifecycle.return_value.start = AsyncMock(return_value=SimpleNamespace(status="running"))
        denied = await client.post(
            ENDPOINTS[1],
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={"action": "start", "server_ids": [str(server_id)]},
        )
        assert denied.status_code == 200
        assert "reason is required" in denied.json()["failed"][0]["error"]
        lifecycle.return_value.start.assert_not_awaited()
        allowed = await client.post(
            ENDPOINTS[1],
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={
                "action": "start",
                "server_ids": [str(server_id)],
                "reason": "Approved maintenance",
            },
        )
    assert allowed.status_code == 200
    assert allowed.json()["succeeded"] == [str(server_id)]
    audit = await db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "server.bulk_start", ActivityLog.target_id == server_id
        )
    )
    assert audit.actor_id == actor_id and audit.details["reason"] == "Approved maintenance"


@pytest.mark.asyncio
async def test_admin_bulk_still_requires_admin_permission_and_valid_uuid(
    client, user_token, admin_token
):
    denied = await client.post(
        ENDPOINTS[0],
        headers={"Authorization": f"Bearer {user_token}"},
        json={"action": "start", "server_ids": []},
    )
    assert denied.status_code == 403
    malformed = await client.post(
        ENDPOINTS[0],
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"action": "start", "server_ids": ["not-a-uuid"]},
    )
    assert malformed.status_code == 400
