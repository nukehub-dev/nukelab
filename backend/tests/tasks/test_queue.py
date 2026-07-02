# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Queue system and billing tasks."""

import pytest


class TestQueueModel:
    """Server queue model tests."""

    @pytest.mark.asyncio
    async def test_queue_model_has_required_fields(self):
        """Queue model should have status, priority, and server_name fields."""
        from app.models.server_queue import ServerQueue

        queue = ServerQueue()
        assert hasattr(queue, "status")
        assert hasattr(queue, "priority")
        assert hasattr(queue, "server_name")


class TestQueueTasks:
    """Celery queue task tests."""

    @pytest.mark.asyncio
    async def test_process_server_queue_task_exists(self):
        """Queue processor celery task should exist."""
        from app.tasks import process_server_queue

        assert process_server_queue is not None


class TestBillingTasks:
    """NUKE billing celery task tests."""

    @pytest.mark.asyncio
    async def test_process_nuke_billing_task_exists(self):
        """Billing task should exist."""
        from app.tasks import process_nuke_billing

        assert process_nuke_billing is not None

    @pytest.mark.asyncio
    async def test_enforce_auto_stop_task_exists(self):
        """Auto-stop task should exist."""
        from app.tasks import enforce_auto_stop

        assert enforce_auto_stop is not None
