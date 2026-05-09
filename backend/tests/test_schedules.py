"""Tests for Server Schedules."""

import pytest


class TestScheduleModel:
    """Schedule model tests."""

    @pytest.mark.asyncio
    async def test_schedule_has_required_fields(self):
        """Schedule model should have cron, action, active, and next_run fields."""
        from app.models.server_schedule import ServerSchedule

        schedule = ServerSchedule()
        assert hasattr(schedule, 'cron_expression')
        assert hasattr(schedule, 'action')
        assert hasattr(schedule, 'is_active')
        assert hasattr(schedule, 'next_run_at')


class TestScheduleService:
    """Schedule service tests."""

    @pytest.mark.asyncio
    async def test_schedule_service_instantiation(self, db_session):
        """Schedule service should be instantiable."""
        from app.services.schedule_service import ScheduleService

        service = ScheduleService(db_session)
        assert service is not None


class TestScheduleTasks:
    """Celery schedule task tests."""

    @pytest.mark.asyncio
    async def test_evaluate_schedules_task_exists(self):
        """Schedule evaluation celery task should exist."""
        from app.tasks import evaluate_schedules

        assert evaluate_schedules is not None
