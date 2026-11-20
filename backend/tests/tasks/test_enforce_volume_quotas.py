# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for volume quota enforcement periodic task."""

from unittest import mock

import pytest


class TestEnforceVolumeQuotas:
    """Tests for enforce_volume_quotas Celery task."""

    def test_task_imports(self):
        """Task should be importable without errors."""
        from app.tasks import enforce_volume_quotas

        assert enforce_volume_quotas is not None

        # Since it's a celery task with _run_async, we just verify it doesn't crash
        # The actual async logic is tested below with mocked DB


class TestVolumeQuotaCheckLogic:
    """Unit tests for the quota check logic used by the task."""

    def test_volume_service_parse_memory(self):
        """VolumeService should parse memory/disk strings correctly."""
        from app.services.volume_service import VolumeService

        # We need a mock db for the constructor
        mock_db = mock.MagicMock()
        service = VolumeService(mock_db)

        assert service._parse_memory("10g") == 10 * 1024**3
        assert service._parse_memory("500m") == 500 * 1024**2
        assert service._parse_memory("1t") == 1 * 1024**4
        assert service._parse_memory("1024") == 1024

    def test_volume_service_human_size(self):
        """VolumeService should format bytes to human-readable strings."""
        from app.services.volume_service import VolumeService

        mock_db = mock.MagicMock()
        service = VolumeService(mock_db)

        assert service._human_size(1024**3) == "1.0 GB"
        assert service._human_size(500 * 1024**2) == "500.0 MB"
        assert service._human_size(1024**4) == "1.0 TB"

    @pytest.mark.asyncio
    async def test_check_volumes_quota_over_limit(self):
        """check_volumes_quota should reject when volume exceeds plan limit."""
        from app.services.volume_service import VolumeService

        mock_db = mock.AsyncMock()
        service = VolumeService(mock_db)

        # Mock volume in DB
        mock_volume = mock.MagicMock()
        mock_volume.id = "vol-1"
        mock_volume.name = "test-vol"
        mock_volume.display_name = "Test Volume"
        mock_volume.size_bytes = 20 * 1024**3  # 20 GB
        mock_volume.max_size_bytes = None

        # Mock DB query result
        mock_result = mock.MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_volume]
        mock_db.execute.return_value = mock_result

        # Mock get_volume_size to return current size
        with mock.patch.object(service, "get_volume_size", return_value=20 * 1024**3):
            result = await service.check_volumes_quota(["vol-1"], "10g")

        assert result["allowed"] is False
        assert "exceeds plan limit" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_volumes_quota_within_limit(self):
        """check_volumes_quota should allow when volume is within plan limit."""
        from app.services.volume_service import VolumeService

        mock_db = mock.AsyncMock()
        service = VolumeService(mock_db)

        mock_volume = mock.MagicMock()
        mock_volume.id = "vol-1"
        mock_volume.name = "test-vol"
        mock_volume.display_name = "Test Volume"
        mock_volume.size_bytes = 5 * 1024**3  # 5 GB
        mock_volume.max_size_bytes = None

        mock_result = mock.MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_volume]
        mock_db.execute.return_value = mock_result

        with mock.patch.object(service, "get_volume_size", return_value=5 * 1024**3):
            result = await service.check_volumes_quota(["vol-1"], "10g")

        assert result["allowed"] is True
