# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin bulk lifecycle actions must not bypass cross-user authorization/audit."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.server import Server


@pytest.mark.asyncio
async def test_admin_bulk_requires_server_write_all(client, admin_token, test_user, db_session):
    """ADMIN_ACCESS alone must not allow cross-user lifecycle mutation."""
    from app.core.permissions import Permission
    from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache

    server = Server(
        name="limited-admin-target",
        user_id=test_user.id,
        status="stopped",
        container_id="limited-admin-container",
    )
    db_session.add(server)
    await db_session.commit()

    ROLE_PERMISSIONS["admin"] = [Permission.ADMIN_ACCESS]
    _rebuild_expansion_cache()

    with patch("app.api.servers._perform_server_start", new_callable=AsyncMock) as action:
        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "start",
                "server_ids": [str(server.id)],
                "reason": "Limited admin must still need server-write authority",
            },
        )

    assert response.status_code == 403
    assert Permission.SERVERS_WRITE_ALL in response.json()["detail"]
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_bulk_requires_reason_and_audit_for_foreign_servers(
    client, admin_token, test_user, db_session
):
    server = Server(
        name="foreign-bulk-target",
        user_id=test_user.id,
        status="stopped",
        container_id="foreign-bulk-container",
    )
    db_session.add(server)
    await db_session.commit()
    sid = str(server.id)
    headers = {"Authorization": f"Bearer {admin_token}"}

    with patch("app.api.servers._perform_server_start", new_callable=AsyncMock) as action:
        missing_reason = await client.post(
            "/api/admin/servers/bulk-action",
            headers=headers,
            json={"action": "start", "server_ids": [sid]},
        )
    assert missing_reason.status_code == 200
    assert missing_reason.json()["results"]["success"] == []
    assert "reason" in missing_reason.json()["results"]["failed"][0]["error"].lower()
    action.assert_not_awaited()

    with (
        patch("app.api.servers._perform_server_start", new_callable=AsyncMock) as action,
        patch("app.api.servers._audit_cross_user_access", new_callable=AsyncMock) as audit,
    ):
        accepted = await client.post(
            "/api/admin/servers/bulk-action",
            headers=headers,
            json={
                "action": "start",
                "server_ids": [sid],
                "reason": "Cross-user support action",
            },
        )
    assert accepted.status_code == 200
    assert accepted.json()["results"]["success"] == [sid]
    audit.assert_awaited_once()
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_bulk_writes_cross_user_audit_and_owner_notification(
    client, admin_token, admin_user, test_user, db_session
):
    server = Server(
        name="audited-bulk-target",
        user_id=test_user.id,
        status="stopped",
        container_id="audited-bulk-container",
    )
    db_session.add(server)
    await db_session.commit()
    reason = "Cross-user maintenance with owner notification"

    with patch("app.api.servers._perform_server_start", new_callable=AsyncMock) as action:
        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "start", "server_ids": [str(server.id)], "reason": reason},
        )

    assert response.status_code == 200
    assert response.json()["results"]["success"] == [str(server.id)]
    action.assert_awaited_once()
    activity = await db_session.scalar(
        select(ActivityLog)
        .where(
            ActivityLog.action == "server.bulk_start",
            ActivityLog.target_id == server.id,
            ActivityLog.actor_id == admin_user.id,
        )
        .execution_options(populate_existing=True)
    )
    assert activity is not None
    assert activity.details["reason"] == reason
    notification = await db_session.scalar(
        select(Notification)
        .where(
            Notification.user_id == test_user.id,
            Notification.action_url == f"/servers/{server.id}",
        )
        .execution_options(populate_existing=True)
    )
    assert notification is not None
    assert notification.extra_data["event_key"] == "server_accessed"
    assert reason in notification.message
