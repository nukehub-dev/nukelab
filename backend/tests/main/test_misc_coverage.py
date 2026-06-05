"""Coverage-focused tests for utility modules and easy wins."""

import pytest
from unittest import mock
from cryptography.fernet import InvalidToken

class TestMain:
    """app/main.py coverage."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        from app.main import root
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        from app.main import health
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

