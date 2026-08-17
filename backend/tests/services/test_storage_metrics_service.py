# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for storage metrics service."""

from unittest import mock

import pytest

from app.services import storage_metrics_service


class TestPostgresDatabaseSize:
    @pytest.mark.asyncio
    async def test_returns_size(self):
        result = mock.Mock()
        result.scalar.return_value = 42
        db = mock.Mock()
        db.execute = mock.AsyncMock(return_value=result)
        result = await storage_metrics_service.get_postgres_database_size(db)
        assert result["status"] == "healthy"
        assert result["size_bytes"] == 42

    @pytest.mark.asyncio
    async def test_handles_error(self):
        db = mock.Mock()
        db.execute = mock.AsyncMock(side_effect=Exception("db down"))
        result = await storage_metrics_service.get_postgres_database_size(db)
        assert result["status"] == "unhealthy"
        assert "error" in result
        assert result["size_bytes"] == 0


class TestRedisMemory:
    @pytest.mark.asyncio
    async def test_returns_memory_with_percent(self):
        redis_client = mock.AsyncMock()
        redis_client.info.return_value = {"used_memory": 80, "maxmemory": 100}
        redis_client.aclose = mock.AsyncMock()

        with mock.patch(
            "app.services.storage_metrics_service.redis.from_url",
            return_value=redis_client,
        ):
            result = await storage_metrics_service.get_redis_memory()

        assert result["status"] == "healthy"
        assert result["used_bytes"] == 80
        assert result["max_bytes"] == 100
        assert result["percent"] == 80.0

    @pytest.mark.asyncio
    async def test_returns_none_percent_when_unlimited(self):
        redis_client = mock.AsyncMock()
        redis_client.info.return_value = {"used_memory": 80, "maxmemory": 0}
        redis_client.aclose = mock.AsyncMock()

        with mock.patch(
            "app.services.storage_metrics_service.redis.from_url",
            return_value=redis_client,
        ):
            result = await storage_metrics_service.get_redis_memory()

        assert result["status"] == "healthy"
        assert result["used_bytes"] == 80
        assert result["max_bytes"] == 0
        assert result["percent"] is None

    @pytest.mark.asyncio
    async def test_handles_error(self):
        with mock.patch(
            "app.services.storage_metrics_service.redis.from_url",
            side_effect=Exception("redis down"),
        ):
            result = await storage_metrics_service.get_redis_memory()

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert result["used_bytes"] == 0
        assert result["max_bytes"] == 0
