"""Tests for Resource Pool service."""

import pytest


class TestResourcePoolService:
    """Resource pool calculation tests."""

    @pytest.mark.asyncio
    async def test_get_available_resources(self, db_session):
        """Resource pool should return CPU, memory, and disk availability."""
        from app.services.resource_pool_service import ResourcePoolService

        service = ResourcePoolService(db_session)
        resources = await service.get_available_resources()

        assert "cpu" in resources
        assert "memory_mb" in resources
        assert "disk_mb" in resources

        assert resources["cpu"]["total"] == 34.0
        assert resources["cpu"]["available"] >= 0

    def test_parse_memory(self):
        """Memory strings should be parsed to megabytes."""
        from app.services.resource_pool_service import ResourcePoolService

        assert ResourcePoolService._parse_memory("2g") == 2048
        assert ResourcePoolService._parse_memory("512m") == 512
        assert ResourcePoolService._parse_memory("1gb") == 1024
