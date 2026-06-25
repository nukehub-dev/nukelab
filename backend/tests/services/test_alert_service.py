"""Tests for AlertService business logic."""

import pytest
import uuid as uuid_mod
from datetime import datetime, timedelta, UTC
from unittest.mock import patch, AsyncMock

from app.services.alert_service import AlertService
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.server_metric import ServerMetric
from app.models.server import Server


class TestAlertServiceExtractMetric:
    """Tests for _extract_metric_value."""

    @pytest.mark.asyncio
    async def test_extract_cpu(self, db_session):
        """Should extract CPU value."""
        service = AlertService(db_session)
        metric = ServerMetric(
            server_id=uuid_mod.uuid4(),
            container_id="container123",
            cpu_percent=45.5,
            memory_percent=60.0,
        )
        assert service._extract_metric_value(metric, "cpu") == 45.5

    @pytest.mark.asyncio
    async def test_extract_memory(self, db_session):
        """Should extract memory value."""
        service = AlertService(db_session)
        metric = ServerMetric(
            server_id=uuid_mod.uuid4(),
            container_id="container123",
            cpu_percent=45.5,
            memory_percent=60.0,
        )
        assert service._extract_metric_value(metric, "memory") == 60.0

    @pytest.mark.asyncio
    async def test_extract_unknown(self, db_session):
        """Should return None for unknown metric type."""
        service = AlertService(db_session)
        metric = ServerMetric(server_id=uuid_mod.uuid4())
        assert service._extract_metric_value(metric, "unknown") is None


class TestAlertServiceGetMetrics:
    """Tests for _get_metrics_for_rule."""

    @pytest.mark.asyncio
    async def test_get_metrics_server_scope(self, db_session, test_user):
        """Should get metrics for specific server."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        metric = ServerMetric(
            server_id=server.id,
            container_id="container123",
            cpu_percent=50.0,
            memory_percent=60.0,
        )
        db_session.add(metric)
        await db_session.commit()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="server",
            target_id=str(server.id),
            threshold=80.0,
            is_active=True,
        )

        service = AlertService(db_session)
        metrics = await service._get_metrics_for_rule(rule)
        assert len(metrics) == 1
        assert metrics[0].server_id == server.id

    @pytest.mark.asyncio
    async def test_get_metrics_user_scope(self, db_session, test_user):
        """Should get metrics for all user servers."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        metric = ServerMetric(
            server_id=server.id,
            container_id="container123",
            cpu_percent=50.0,
        )
        db_session.add(metric)
        await db_session.commit()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="user",
            target_id=str(test_user.id),
            threshold=80.0,
            is_active=True,
        )

        service = AlertService(db_session)
        metrics = await service._get_metrics_for_rule(rule)
        assert len(metrics) >= 1

    @pytest.mark.asyncio
    async def test_get_metrics_global_scope(self, db_session, test_user):
        """Should get recent metrics globally."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        metric = ServerMetric(
            server_id=server.id,
            container_id="container123",
            cpu_percent=50.0,
        )
        db_session.add(metric)
        await db_session.commit()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="global",
            threshold=80.0,
            is_active=True,
        )

        service = AlertService(db_session)
        metrics = await service._get_metrics_for_rule(rule)
        assert len(metrics) >= 1


class TestAlertServiceAcknowledge:
    """Tests for acknowledge_alert."""

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, db_session, test_user):
        """Should acknowledge an alert."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        rule = AlertRule(
            name="Test",
            metric_type="cpu",
            operator="gt",
            threshold=80.0,
            scope="global",
            is_active=True,
        )
        db_session.add(rule)
        await db_session.flush()

        alert = AlertHistory(
            rule_id=rule.id,
            server_id=server.id,
            status="fired",
            metric_value=90.0,
            threshold=80.0,
        )
        db_session.add(alert)
        await db_session.commit()

        service = AlertService(db_session)
        result = await service.acknowledge_alert(
            str(alert.id), str(test_user.id), notes="Looking into it"
        )
        assert result is not None
        assert result.status == "acknowledged"
        assert result.acknowledged_by == test_user.id
        assert result.notes == "Looking into it"

    @pytest.mark.asyncio
    async def test_acknowledge_alert_not_found(self, db_session, test_user):
        """Should return None for missing alert."""
        service = AlertService(db_session)
        result = await service.acknowledge_alert(str(uuid_mod.uuid4()), str(test_user.id))
        assert result is None


class TestAlertServiceResolve:
    """Tests for resolve_alert."""

    @pytest.mark.asyncio
    async def test_resolve_alert(self, db_session, test_user):
        """Should resolve an alert."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        rule = AlertRule(
            name="Test",
            metric_type="cpu",
            operator="gt",
            threshold=80.0,
            scope="global",
            is_active=True,
        )
        db_session.add(rule)
        await db_session.flush()

        alert = AlertHistory(
            rule_id=rule.id,
            server_id=server.id,
            status="fired",
            metric_value=90.0,
            threshold=80.0,
        )
        db_session.add(alert)
        await db_session.commit()

        service = AlertService(db_session)
        result = await service.resolve_alert(str(alert.id), resolved_value=45.0)
        assert result is not None
        assert result.status == "resolved"
        assert result.resolved_value == 45.0
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_alert_not_found(self, db_session):
        """Should return None for missing alert."""
        service = AlertService(db_session)
        result = await service.resolve_alert(str(uuid_mod.uuid4()))
        assert result is None


class TestAlertServiceEvaluate:
    """Tests for evaluate methods."""

    @pytest.mark.asyncio
    async def test_evaluate_all_rules_empty(self, db_session):
        """Should handle no active rules."""
        service = AlertService(db_session)
        await service.evaluate_all_rules()  # Should not raise

    @pytest.mark.asyncio
    async def test_handle_breach_creates_alert(self, db_session, test_user):
        """Should create alert on breach."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="server",
            target_id=str(server.id),
            threshold=50.0,
            cooldown_seconds=0,
            is_active=True,
        )
        db_session.add(rule)
        await db_session.flush()

        metric = ServerMetric(
            server_id=server.id,
            container_id="container123",
            cpu_percent=75.0,
        )

        service = AlertService(db_session)
        await service._handle_breach(rule, metric, 75.0)

        alerts = await db_session.execute(
            __import__("sqlalchemy", fromlist=["select"])
            .select(AlertHistory)
            .where(AlertHistory.rule_id == rule.id)
        )
        alert = alerts.scalar_one_or_none()
        assert alert is not None
        assert alert.metric_value == 75.0

    @pytest.mark.asyncio
    async def test_check_resolution_resolves_alert(self, db_session, test_user):
        """Should resolve alert when value drops."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="server",
            target_id=str(server.id),
            threshold=50.0,
            is_active=True,
        )
        db_session.add(rule)
        await db_session.flush()

        alert = AlertHistory(
            rule_id=rule.id,
            server_id=server.id,
            status="fired",
            metric_value=75.0,
            threshold=50.0,
        )
        db_session.add(alert)
        await db_session.commit()

        metric = ServerMetric(server_id=server.id, cpu_percent=30.0)

        service = AlertService(db_session)
        await service._check_resolution(rule, metric, 30.0)

        assert alert.status == "resolved"
        assert alert.resolved_value == 30.0

    @pytest.mark.asyncio
    async def test_handle_breach_respects_cooldown(self, db_session, test_user):
        """Should not create duplicate alert during cooldown."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        rule = AlertRule(
            name="CPU Alert",
            operator="gt",
            metric_type="cpu",
            scope="server",
            target_id=str(server.id),
            threshold=50.0,
            cooldown_seconds=3600,
            is_active=True,
        )
        db_session.add(rule)
        await db_session.flush()

        alert = AlertHistory(
            rule_id=rule.id,
            server_id=server.id,
            status="fired",
            metric_value=75.0,
            threshold=50.0,
            fired_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db_session.add(alert)
        await db_session.commit()

        metric = ServerMetric(server_id=server.id, cpu_percent=75.0)

        service = AlertService(db_session)
        await service._handle_breach(rule, metric, 75.0)

        # Should still only have 1 alert
        alerts = await db_session.execute(
            __import__("sqlalchemy", fromlist=["select", "func"])
            .select(__import__("sqlalchemy", fromlist=["func"]).func.count())
            .select_from(AlertHistory)
            .where(AlertHistory.rule_id == rule.id)
        )
        assert alerts.scalar() == 1
