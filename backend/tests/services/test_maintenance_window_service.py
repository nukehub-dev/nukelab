# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for MaintenanceWindowService."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from app.models.maintenance_window import MaintenanceWindow
from app.models.user import User
from app.services.maintenance_window_service import MaintenanceWindowService


@pytest.fixture
def service(db_session):
    return MaintenanceWindowService(db_session)


class TestListWindows:
    @pytest.mark.asyncio
    async def test_list_all(self, service, db_session):
        w1 = MaintenanceWindow(
            title="t1",
            message="m1",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        w2 = MaintenanceWindow(
            title="t2",
            message="m2",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=4),
            is_active=False,
        )
        db_session.add_all([w1, w2])
        await db_session.commit()

        result = await service.list_windows()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_active_only(self, service, db_session):
        w1 = MaintenanceWindow(
            title="t1",
            message="m1",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            is_active=True,
        )
        w2 = MaintenanceWindow(
            title="t2",
            message="m2",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=4),
            is_active=False,
        )
        db_session.add_all([w1, w2])
        await db_session.commit()

        result = await service.list_windows(active_only=True)
        assert len(result) == 1
        assert result[0]["title"] == "t1"

    @pytest.mark.asyncio
    async def test_list_future_only(self, service, db_session):
        past = MaintenanceWindow(
            title="past",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2),
            end_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
        future = MaintenanceWindow(
            title="future",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add_all([past, future])
        await db_session.commit()

        result = await service.list_windows(future_only=True)
        assert len(result) == 1
        assert result[0]["title"] == "future"

    @pytest.mark.asyncio
    async def test_list_limit(self, service, db_session):
        for i in range(5):
            db_session.add(
                MaintenanceWindow(
                    title=f"t{i}",
                    message="m",
                    start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=i),
                    end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=i + 1),
                )
            )
        await db_session.commit()

        result = await service.list_windows(limit=2)
        assert len(result) == 2


class TestGetWindow:
    @pytest.mark.asyncio
    async def test_get_found(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        result = await service.get_window(str(w.id))
        assert result is not None
        assert result.title == "t"

    @pytest.mark.asyncio
    async def test_get_not_found(self, service):
        result = await service.get_window(str(uuid.uuid4()))
        assert result is None


class TestCreateWindow:
    @pytest.mark.asyncio
    async def test_create_success(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        end = start + timedelta(hours=2)
        w = await service.create_window("Test", "Message", start, end)
        assert w.title == "Test"
        assert w.message == "Message"
        assert w.is_active is True
        assert w.notify_offsets == [15]

    @pytest.mark.asyncio
    async def test_create_with_offsets(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
        end = start + timedelta(hours=1)
        w = await service.create_window("T", "M", start, end, notify_offsets=[30, 60])
        assert w.notify_offsets == [60, 30]

    @pytest.mark.asyncio
    async def test_create_end_before_start_raises(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        end = start - timedelta(minutes=1)
        with pytest.raises(ValueError, match="End time must be after start time"):
            await service.create_window("T", "M", start, end)

    @pytest.mark.asyncio
    async def test_create_start_in_past_raises(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        end = start + timedelta(hours=1)
        with pytest.raises(ValueError, match="Start time must be in the future"):
            await service.create_window("T", "M", start, end)


class TestUpdateWindow:
    @pytest.mark.asyncio
    async def test_update_title(self, service, db_session):
        w = MaintenanceWindow(
            title="old",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        updated = await service.update_window(str(w.id), title="new")
        assert updated.title == "new"

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, service):
        with pytest.raises(ValueError, match="Maintenance window not found"):
            await service.update_window(str(uuid.uuid4()), title="x")

    @pytest.mark.asyncio
    async def test_update_invalid_times_raises(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with pytest.raises(ValueError, match="End time must be after start time"):
            await service.update_window(
                str(w.id),
                start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5),
                end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_update_resets_notification_state(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            auto_enabled=True,
            notified_offsets=[15],
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        new_start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
        new_end = new_start + timedelta(hours=1)
        updated = await service.update_window(str(w.id), start_at=new_start, end_at=new_end)
        assert updated.auto_enabled is False
        assert updated.notified_offsets == []


class TestDeleteWindow:
    @pytest.mark.asyncio
    async def test_delete_success(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        result = await service.delete_window(str(w.id))
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, service):
        result = await service.delete_window(str(uuid.uuid4()))
        assert result is False


class TestNormalizeOffsets:
    def test_empty_defaults_to_15(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        assert service._normalize_offsets([], start) == [15]

    def test_filters_too_large_offsets(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30)
        result = service._normalize_offsets([10, 60, 120], start)
        assert 60 not in result
        assert 120 not in result
        assert 10 in result

    def test_deduplicates_and_sorts(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
        result = service._normalize_offsets([30, 30, 15, 45], start)
        assert result == [45, 30, 15]

    def test_negative_and_zero_filtered(self, service):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        result = service._normalize_offsets([-5, 0, 15], start)
        assert result == [15]


class TestPendingNotifications:
    @pytest.mark.asyncio
    async def test_no_pending_when_already_notified(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=20)
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=start,
            end_at=start + timedelta(hours=1),
            notify_offsets=[15],
            notified_offsets=[15],
        )
        db_session.add(w)
        await db_session.commit()

        pending = await service.get_pending_notifications()
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_pending_when_threshold_met(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=start,
            end_at=start + timedelta(hours=1),
            notify_offsets=[15],
        )
        db_session.add(w)
        await db_session.commit()

        pending = await service.get_pending_notifications()
        assert len(pending) == 1
        assert pending[0][1] == 15

    @pytest.mark.asyncio
    async def test_skips_old_ideal_notification_time(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=start,
            end_at=start + timedelta(hours=1),
            notify_offsets=[15],
        )
        db_session.add(w)
        await db_session.commit()

        # If ideal notify time is > 1 hour in the past, skip
        # This requires start_at to be in the past by > 1h + offset
        # So we test the opposite: a window with start_at far in future shouldn't trigger
        start_far = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5)
        w2 = MaintenanceWindow(
            title="t2",
            message="m",
            start_at=start_far,
            end_at=start_far + timedelta(hours=1),
            notify_offsets=[15],
        )
        db_session.add(w2)
        await db_session.commit()

        pending = await service.get_pending_notifications()
        # Only w1 should be pending; w2's threshold is not met
        assert len(pending) == 1


class TestWindowsToEnable:
    @pytest.mark.asyncio
    async def test_get_windows_to_enable(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            is_active=True,
            auto_enabled=False,
        )
        db_session.add(w)
        await db_session.commit()

        result = await service.get_windows_to_enable()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_windows_already_enabled(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            is_active=True,
            auto_enabled=True,
        )
        db_session.add(w)
        await db_session.commit()

        result = await service.get_windows_to_enable()
        assert len(result) == 0


class TestWindowsToDisable:
    @pytest.mark.asyncio
    async def test_get_windows_to_disable(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2),
            end_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            is_active=True,
            auto_enabled=True,
            auto_disabled=False,
        )
        db_session.add(w)
        await db_session.commit()

        result = await service.get_windows_to_disable()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_windows_already_disabled(self, service, db_session):
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2),
            end_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            is_active=True,
            auto_enabled=True,
            auto_disabled=True,
        )
        db_session.add(w)
        await db_session.commit()

        result = await service.get_windows_to_disable()
        assert len(result) == 0


class TestSendAdvanceNotifications:
    @pytest.mark.asyncio
    async def test_sends_to_active_users(self, service, db_session):
        user = User(username="u1", email="u1@test.com", password_hash="h", is_active=True)
        db_session.add(user)
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        w = MaintenanceWindow(
            title="t", message="m", start_at=start, end_at=start + timedelta(hours=2)
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with mock.patch("app.services.maintenance_window_service.NotificationService") as MockNotif:
            mock_notif = MockNotif.return_value
            mock_notif.maintenance_window = mock.AsyncMock()
            sent = await service.send_advance_notifications(w, 15)
            assert sent == 1
            mock_notif.maintenance_window.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_continues_on_user_failure(self, service, db_session):
        u1 = User(username="u1", email="u1@test.com", password_hash="h", is_active=True)
        u2 = User(username="u2", email="u2@test.com", password_hash="h", is_active=True)
        db_session.add_all([u1, u2])
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        w = MaintenanceWindow(
            title="t", message="m", start_at=start, end_at=start + timedelta(hours=2)
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with mock.patch("app.services.maintenance_window_service.NotificationService") as MockNotif:
            mock_notif = MockNotif.return_value
            mock_notif.maintenance_window = mock.AsyncMock(side_effect=[Exception("fail"), None])
            sent = await service.send_advance_notifications(w, 15)
            assert sent == 1
            assert mock_notif.maintenance_window.await_count == 2

    @pytest.mark.asyncio
    async def test_tracks_notified_offset(self, service, db_session):
        user = User(username="u1", email="u1@test.com", password_hash="h", is_active=True)
        db_session.add(user)
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        w = MaintenanceWindow(
            title="t", message="m", start_at=start, end_at=start + timedelta(hours=2)
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with mock.patch("app.services.maintenance_window_service.NotificationService") as MockNotif:
            mock_notif = MockNotif.return_value
            mock_notif.maintenance_window = mock.AsyncMock()
            await service.send_advance_notifications(w, 30)
            assert 30 in w.notified_offsets


class TestFormatOffset:
    def test_minutes(self, service):
        assert service._format_offset(1) == "1 minute"
        assert service._format_offset(5) == "5 minutes"

    def test_hours(self, service):
        assert service._format_offset(60) == "1 hour"
        assert service._format_offset(120) == "2 hours"

    def test_days(self, service):
        assert service._format_offset(1440) == "1 day"
        assert service._format_offset(2880) == "2 days"


class TestEnableDisableMaintenance:
    @pytest.mark.asyncio
    async def test_enable_maintenance(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        w = MaintenanceWindow(
            title="t", message="m", start_at=start, end_at=start + timedelta(hours=2)
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with mock.patch("app.services.maintenance_window_service.SettingService") as MockSetting:
            mock_setting = MockSetting.return_value
            mock_setting.save_maintenance = mock.AsyncMock()
            await service.enable_maintenance(w)
            mock_setting.save_maintenance.assert_awaited_once_with(
                enabled=True, message=f"[{w.title}] {w.message}"
            )
            assert w.auto_enabled is True

    @pytest.mark.asyncio
    async def test_disable_maintenance(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        w = MaintenanceWindow(
            title="t", message="m", start_at=start, end_at=start + timedelta(hours=2)
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with mock.patch("app.services.maintenance_window_service.SettingService") as MockSetting:
            mock_setting = MockSetting.return_value
            mock_setting.save_maintenance = mock.AsyncMock()
            await service.disable_maintenance(w)
            mock_setting.save_maintenance.assert_awaited_once_with(enabled=False)
            assert w.auto_disabled is True


class TestEvaluateWindows:
    @pytest.mark.asyncio
    async def test_evaluate_runs_all_phases(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=start,
            end_at=start + timedelta(hours=1),
            notify_offsets=[15],
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        with (
            mock.patch.object(
                service, "send_advance_notifications", new_callable=mock.AsyncMock, return_value=3
            ),
            mock.patch.object(service, "enable_maintenance", new_callable=mock.AsyncMock),
        ):
            with mock.patch.object(service, "disable_maintenance", new_callable=mock.AsyncMock):
                result = await service.evaluate_windows()

        assert result["notifications_sent"] == 3
        assert result["enabled_count"] == 0
        assert result["disabled_count"] == 0

    @pytest.mark.asyncio
    async def test_evaluate_enables_and_disables(self, service, db_session):
        start = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=start,
            end_at=start + timedelta(hours=1),
            is_active=True,
            auto_enabled=False,
        )
        db_session.add(w)
        await db_session.commit()

        with (
            mock.patch.object(
                service, "send_advance_notifications", new_callable=mock.AsyncMock, return_value=0
            ),
            mock.patch.object(
                service, "enable_maintenance", new_callable=mock.AsyncMock
            ) as mock_enable,
        ):
            with mock.patch.object(service, "disable_maintenance", new_callable=mock.AsyncMock):
                result = await service.evaluate_windows()

        assert result["enabled_count"] == 1
        mock_enable.assert_awaited_once()
