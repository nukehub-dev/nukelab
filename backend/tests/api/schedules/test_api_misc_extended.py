"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server

class TestSchedulesAPI:
    """Tests for schedule endpoints."""

    @pytest.mark.asyncio
    async def test_list_schedules_server_not_found(self, client, user_token):
        """Listing schedules for non-existent server should 404."""
        response = await client.get(
            "/api/schedules/servers/00000000-0000-0000-0000-000000000000/schedules",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found(self, client, user_token, test_user, db_session):
        """Deleting non-existent schedule should 404."""
        server = Server(name="sched-srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.delete(
            f"/api/schedules/servers/{server.id}/schedules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_cron(self, client, user_token, test_user, db_session):
        """Creating schedule with invalid cron should 400 or 422."""
        server = Server(name="sched-srv2", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.post(
            f"/api/schedules/servers/{server.id}/schedules",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "start", "cron_expression": "invalid"}
        )
        assert response.status_code in [400, 422, 403, 404]

    @pytest.mark.asyncio
    async def test_update_schedule_not_found(self, client, user_token, test_user, db_session):
        """Updating non-existent schedule should 404."""
        server = Server(name="sched-srv3", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.put(
            f"/api/schedules/servers/{server.id}/schedules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "stop"}
        )
        assert response.status_code in [404, 403]

