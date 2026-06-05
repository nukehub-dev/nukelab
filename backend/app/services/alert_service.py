from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.server_metric import ServerMetric
from app.models.user import User


class AlertService:
    """Evaluate alert rules and manage alert lifecycle"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_all_rules(self):
        """Evaluate all active alert rules against latest metrics"""
        result = await self.db.execute(
            select(AlertRule).where(AlertRule.is_active == True)
        )
        rules = result.scalars().all()

        for rule in rules:
            try:
                await self._evaluate_rule(rule)
            except Exception as e:
                print(f"Error evaluating rule {rule.id}: {e}")

    async def _evaluate_rule(self, rule: AlertRule):
        """Evaluate a single rule"""
        metrics = await self._get_metrics_for_rule(rule)

        for metric in metrics:
            value = self._extract_metric_value(metric, rule.metric_type)
            if value is None:
                continue

            if rule.evaluate(value):
                await self._handle_breach(rule, metric, value)
            else:
                await self._check_resolution(rule, metric, value)

    async def _handle_breach(self, rule: AlertRule, metric: ServerMetric, value: float):
        """Handle threshold breach"""
        # Check cooldown
        cooldown_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=rule.cooldown_seconds)
        recent_alert = await self.db.execute(
            select(AlertHistory).where(
                and_(
                    AlertHistory.rule_id == rule.id,
                    AlertHistory.server_id == metric.server_id,
                    AlertHistory.status.in_(["fired", "acknowledged"]),
                    AlertHistory.fired_at >= cooldown_time
                )
            )
        )

        if recent_alert.scalar_one_or_none():
            return

        alert = AlertHistory(
            rule_id=rule.id,
            server_id=metric.server_id,
            metric_value=value,
            threshold=rule.threshold,
        )

        self.db.add(alert)
        await self.db.commit()
        await self._send_notifications(rule, alert)

    async def _check_resolution(self, rule: AlertRule, metric: ServerMetric, value: float):
        """Check if an active alert can be resolved"""
        result = await self.db.execute(
            select(AlertHistory).where(
                and_(
                    AlertHistory.rule_id == rule.id,
                    AlertHistory.server_id == metric.server_id,
                    AlertHistory.status.in_(["fired", "acknowledged"]),
                )
            ).order_by(AlertHistory.fired_at.desc())
        )
        active_alert = result.scalar_one_or_none()

        if active_alert:
            active_alert.status = "resolved"
            active_alert.resolved_at = datetime.now(UTC).replace(tzinfo=None)
            active_alert.resolved_value = value
            await self.db.commit()

    async def _send_notifications(self, rule: AlertRule, alert: AlertHistory):
        """Send notifications for an alert"""
        from app.services.email_service import EmailService
        from app.services.notification_service import NotificationService

        result = await self.db.execute(
            select(User).where(User.id == alert.server_id)
        )
        user = result.scalar_one_or_none()

        if rule.notify_admin:
            alert.admin_notified = True

        if rule.notify_user and user:
            alert.user_notified = True
            # Create in-app notification
            notif_service = NotificationService(self.db)
            await notif_service.create(
                user_id=user.id,
                title=f"Alert: {rule.name}",
                message=f"{rule.metric_type.upper()} exceeded threshold ({alert.metric_value:.1f} > {rule.threshold:.1f})",
                type="system",
                severity="warning",
                action_url=f"/servers/{alert.server_id}"
            )

        if rule.email_enabled and user and user.email:
            email_service = EmailService()
            if email_service.enabled:
                template = email_service.render_template("server_ready", {
                    "username": user.username,
                    "server_name": rule.name,
                    "message": f"{rule.metric_type.upper()} alert: {alert.metric_value:.1f} (threshold: {rule.threshold:.1f})"
                })
                result = await email_service.send_email(
                    to_email=user.email,
                    subject=f"[NukeLab Alert] {rule.name}",
                    html_body=template,
                    text_body=f"Alert: {rule.name}\n{rule.metric_type.upper()}: {alert.metric_value:.1f} (threshold: {rule.threshold:.1f})"
                )
                if result["success"]:
                    alert.email_sent = True

        if rule.webhook_url:
            alert.webhook_sent = True

        await self.db.commit()

    async def _get_metrics_for_rule(self, rule: AlertRule) -> List[ServerMetric]:
        """Get latest metrics based on rule scope"""
        if rule.scope == "server" and rule.target_id:
            result = await self.db.execute(
                select(ServerMetric).where(
                    ServerMetric.server_id == rule.target_id
                ).order_by(ServerMetric.collected_at.desc()).limit(1)
            )
            metric = result.scalar_one_or_none()
            return [metric] if metric else []
        elif rule.scope == "user" and rule.target_id:
            # Get all servers for user
            from app.models.server import Server
            server_result = await self.db.execute(
                select(Server.id).where(Server.user_id == rule.target_id)
            )
            server_ids = [s[0] for s in server_result.all()]
            if not server_ids:
                return []
            result = await self.db.execute(
                select(ServerMetric).where(
                    ServerMetric.server_id.in_(server_ids)
                ).order_by(ServerMetric.collected_at.desc())
            )
            return result.scalars().all()
        else:
            # Global - all recent metrics
            result = await self.db.execute(
                select(ServerMetric).order_by(ServerMetric.collected_at.desc()).limit(100)
            )
            return result.scalars().all()

    def _extract_metric_value(self, metric: ServerMetric, metric_type: str) -> Optional[float]:
        """Extract the relevant value from a metric based on type"""
        mapping = {
            'cpu': metric.cpu_percent,
            'memory': metric.memory_percent,
            'disk': metric.disk_read_bytes,
            'gpu': metric.gpu_percent,
            'pids': metric.pids,
        }
        return mapping.get(metric_type)

    async def acknowledge_alert(self, alert_id: str, user_id: str, notes: Optional[str] = None):
        """Acknowledge an alert"""
        from sqlalchemy.dialects.postgresql import UUID
        import uuid

        result = await self.db.execute(
            select(AlertHistory).where(AlertHistory.id == uuid.UUID(alert_id))
        )
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        alert.status = "acknowledged"
        alert.acknowledged_by = uuid.UUID(user_id)
        alert.acknowledged_at = datetime.now(UTC).replace(tzinfo=None)
        if notes:
            alert.notes = notes

        await self.db.commit()
        return alert

    async def resolve_alert(self, alert_id: str, resolved_value: Optional[float] = None):
        """Resolve an alert"""
        import uuid

        result = await self.db.execute(
            select(AlertHistory).where(AlertHistory.id == uuid.UUID(alert_id))
        )
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        alert.status = "resolved"
        alert.resolved_at = datetime.now(UTC).replace(tzinfo=None)
        if resolved_value is not None:
            alert.resolved_value = resolved_value

        await self.db.commit()
        return alert
