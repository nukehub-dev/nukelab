"""Tests for Analytics service and API."""

import pytest
from httpx import AsyncClient


class TestAnalyticsService:
    """Analytics service tests."""

    @pytest.mark.asyncio
    async def test_analytics_service_instantiation(self, db_session):
        """Analytics service should be instantiable."""
        from app.services.analytics_service import AnalyticsService

        service = AnalyticsService(db_session)
        assert service is not None


class TestAnalyticsAPI:
    """Analytics API endpoint tests."""

    @pytest.mark.asyncio
    async def test_analytics_requires_admin(self, client: AsyncClient, test_user, user_token):
        """Analytics endpoints should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.get("/api/analytics/global", headers=headers)
        assert resp.status_code == 403
