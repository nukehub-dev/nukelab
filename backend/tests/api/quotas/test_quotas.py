"""Tests for Quotas API endpoints."""

import pytest
from unittest import mock
import uuid

from app.models.resource_quota import ResourceQuota


class TestQuotaAdminEndpoints:
    """Tests for admin-only quota endpoints."""

    @pytest.mark.asyncio
    async def test_list_all_quotas_as_admin(self, client, admin_token, db_session):
        """Admin should be able to list all quotas."""
        response = await client.get(
            "/api/quotas/all",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    @pytest.mark.asyncio
    async def test_list_all_quotas_pagination(self, client, admin_token, db_session):
        """Should support page and limit params."""
        response = await client.get(
            "/api/quotas/all?page=1&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_all_quotas_search(self, client, admin_token, db_session):
        """Should support search param."""
        response = await client.get(
            "/api/quotas/all?search=test",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_all_quotas_forbidden_for_user(self, client, user_token):
        """Regular user should not access admin quota list."""
        response = await client.get(
            "/api/quotas/all",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_my_quota(self, client, support_token, support_user, db_session):
        """Support user should get their own quota."""
        quota = ResourceQuota(user_id=support_user.id, max_cpu_total=2.0, max_memory_total="8g")
        db_session.add(quota)
        await db_session.commit()

        with mock.patch("app.api.quotas.QuotaService.recalculate_usage", return_value=quota):
            response = await client.get(
                "/api/quotas/",
                headers={"Authorization": f"Bearer {support_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    @pytest.mark.asyncio
    async def test_check_spawn_allowed(self, client, support_token, support_user, db_session):
        """Support user should be able to check spawn allowance."""
        quota = ResourceQuota(user_id=support_user.id, max_cpu_total=2.0)
        db_session.add(quota)
        await db_session.commit()

        with mock.patch("app.api.quotas.QuotaService.check_spawn_allowed", return_value={"allowed": True, "reason": None}):
            response = await client.post(
                "/api/quotas/check",
                headers={"Authorization": f"Bearer {support_token}"},
                json={"plan_id": str(support_user.id)}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_spawn_forbidden_for_user(self, client, user_token):
        """Regular user without QUOTA_READ should not access check spawn."""
        response = await client.post(
            "/api/quotas/check",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"plan_id": str(uuid.uuid4())}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_quota_as_admin(self, client, admin_token, test_user, db_session):
        """Admin should get specific user's quota."""
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=4.0,
            max_memory_total="16g",
        )
        db_session.add(quota)
        await db_session.commit()

        with mock.patch("app.api.quotas.QuotaService.recalculate_usage", return_value=quota):
            response = await client.get(
                f"/api/quotas/{test_user.id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_user_quota_forbidden_for_user(self, client, user_token, test_user):
        """Regular user should not access other user's quota by ID."""
        other_user_id = str(uuid.uuid4())
        response = await client.get(
            f"/api/quotas/{other_user_id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_user_quota_as_admin(self, client, admin_token, test_user, db_session):
        """Admin should be able to update user quota."""
        quota = ResourceQuota(user_id=test_user.id, max_cpu_total=2.0)
        db_session.add(quota)
        await db_session.commit()

        with mock.patch("app.api.quotas.QuotaService.update_user_quota", return_value=quota):
            response = await client.put(
                f"/api/quotas/{test_user.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"max_cpu_total": 8.0, "max_servers_total": 10}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Quota updated"

    @pytest.mark.asyncio
    async def test_update_user_quota_forbidden_for_user(self, client, user_token, test_user):
        """Regular user should not update quotas."""
        response = await client.put(
            f"/api/quotas/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"max_cpu_total": 8.0}
        )
        assert response.status_code == 403

"""Coverage tests for smaller API modules: health, system, quotas, ip_restriction."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC

class TestQuotasEndpoints:
    """app/api/quotas.py coverage."""

    @pytest.mark.asyncio
    async def test_get_my_quota_admin(self, client, admin_token):
        response = await client.get(
            "/api/quotas/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    @pytest.mark.asyncio
    async def test_list_all_quotas_admin(self, client, admin_token):
        response = await client.get(
            "/api/quotas/all",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True





"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server

class TestQuotasAPI:
    """Tests for quota endpoints."""

    @pytest.mark.asyncio
    async def test_get_my_quota(self, client, admin_token, admin_user):
        """Admin should get quota."""
        response = await client.get(
            "/api/quotas/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_check_spawn_allowed(self, client, admin_token):
        """Should check if spawn is allowed."""
        response = await client.post(
            "/api/quotas/check",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_id": "00000000-0000-0000-0000-000000000000"}
        )
        # May succeed or fail depending on quota state
        assert response.status_code in [200, 400, 404, 422]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_all_quotas(self, client, user_token):
        """Regular user should not list all quotas."""
        response = await client.get(
            "/api/quotas/all",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_quota(self, client, user_token):
        """Regular user should not update quotas."""
        response = await client.put(
            "/api/quotas/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"max_servers_total": 10}
        )
        assert response.status_code in [403, 404]



