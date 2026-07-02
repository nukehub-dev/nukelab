# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for user activity feed endpoint."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.activity_log import ActivityLog


class TestUserActivityAPI:
    """Tests for GET /users/me/activity"""

    @pytest.mark.asyncio
    async def test_list_own_activity(self, client, test_user, user_token, db_session):
        """Should return paginated activity for the current user."""
        # Seed activity logs
        for _i in range(3):
            log = ActivityLog(
                actor_id=test_user.id,
                action="create_servers",
                target_type="servers",
                target_id=uuid.uuid4(),
                details={"method": "POST", "status_code": 201},
            )
            db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "activities" in data
        assert "pagination" in data
        assert len(data["activities"]) == 3
        assert data["pagination"]["total"] == 3
        assert data["pagination"]["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_action(self, client, test_user, user_token, db_session):
        """Should filter activities by action using partial match."""
        log1 = ActivityLog(
            actor_id=test_user.id,
            action="create_servers",
            target_type="servers",
            target_id=uuid.uuid4(),
            details={},
        )
        log2 = ActivityLog(
            actor_id=test_user.id,
            action="update_users",
            target_type="users",
            target_id=uuid.uuid4(),
            details={},
        )
        log3 = ActivityLog(
            actor_id=test_user.id,
            action="create_volumes",
            target_type="volumes",
            target_id=uuid.uuid4(),
            details={},
        )
        db_session.add_all([log1, log2, log3])
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?action=create",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 2
        actions = [a["action"] for a in data["activities"]]
        assert "create_servers" in actions
        assert "create_volumes" in actions
        assert "update_users" not in actions

    @pytest.mark.asyncio
    async def test_filter_by_target_type(self, client, test_user, user_token, db_session):
        """Should filter activities by target_type."""
        log1 = ActivityLog(
            actor_id=test_user.id,
            action="start_servers",
            target_type="servers",
            target_id=uuid.uuid4(),
            details={},
        )
        log2 = ActivityLog(
            actor_id=test_user.id,
            action="update_users",
            target_type="users",
            target_id=uuid.uuid4(),
            details={},
        )
        db_session.add_all([log1, log2])
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?target_type=servers",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 1
        assert data["activities"][0]["target_type"] == "servers"

    @pytest.mark.asyncio
    async def test_pagination(self, client, test_user, user_token, db_session):
        """Should return correct page of results."""
        for i in range(5):
            log = ActivityLog(
                actor_id=test_user.id,
                action=f"action_{i}",
                target_type="servers",
                target_id=uuid.uuid4(),
                details={},
            )
            db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity?page=1&limit=2",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["activities"]) == 2
        assert data["pagination"]["total"] == 5
        assert data["pagination"]["total_pages"] == 3

        # Page 2
        response = await client.get(
            "/api/users/me/activity?page=2&limit=2",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        data = response.json()
        assert len(data["activities"]) == 2

        # Page 3 (last page)
        response = await client.get(
            "/api/users/me/activity?page=3&limit=2",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        data = response.json()
        assert len(data["activities"]) == 1

    @pytest.mark.asyncio
    async def test_does_not_show_other_users_activity(
        self, client, test_user, user_token, admin_user, db_session
    ):
        """Should only return activity for the authenticated user."""
        own_log = ActivityLog(
            actor_id=test_user.id,
            action="create_servers",
            target_type="servers",
            target_id=uuid.uuid4(),
            details={},
        )
        other_log = ActivityLog(
            actor_id=admin_user.id,
            action="delete_users",
            target_type="users",
            target_id=uuid.uuid4(),
            details={},
        )
        db_session.add_all([own_log, other_log])
        await db_session.commit()

        response = await client.get(
            "/api/users/me/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 1
        assert data["activities"][0]["action"] == "create_servers"

    @pytest.mark.asyncio
    async def test_filter_by_date_range(self, client, test_user, user_token, db_session):
        """Should filter activities by from_date and to_date."""
        old_log = ActivityLog(
            actor_id=test_user.id,
            action="old_action",
            target_type="servers",
            target_id=uuid.uuid4(),
            details={},
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        )
        new_log = ActivityLog(
            actor_id=test_user.id,
            action="new_action",
            target_type="servers",
            target_id=uuid.uuid4(),
            details={},
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add_all([old_log, new_log])
        await db_session.commit()

        from_date = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        response = await client.get(
            f"/api/users/me/activity?from_date={from_date}",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 1
        assert data["activities"][0]["action"] == "new_action"

    @pytest.mark.asyncio
    async def test_empty_result(self, client, test_user, user_token):
        """Should return empty list when no activity exists."""
        response = await client.get(
            "/api/users/me/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["activities"] == []
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["total_pages"] == 0

    @pytest.mark.asyncio
    async def test_unauthorized(self, client):
        """Should reject requests without auth token."""
        response = await client.get("/api/users/me/activity")
        assert response.status_code == 401
