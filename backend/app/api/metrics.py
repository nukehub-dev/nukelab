from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from pydantic import BaseModel

from app.api.auth import get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.dependencies import PermissionChecker, require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.system_metric import SystemMetric
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.health_check import HealthCheck
from app.services.alert_service import AlertService

router = APIRouter()


# ========== Pydantic Schemas ==========

class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    metric_type: str
    operator: str
    threshold: float
    scope: str = "global"
    target_id: Optional[str] = None
    duration_seconds: int = 60
    cooldown_seconds: int = 300
    notify_admin: bool = True
    notify_user: bool = True
    email_enabled: bool = False
    webhook_url: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metric_type: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    is_active: Optional[bool] = None
    duration_seconds: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    notify_admin: Optional[bool] = None
    notify_user: Optional[bool] = None
    email_enabled: Optional[bool] = None
    webhook_url: Optional[str] = None


class AlertAcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


# ========== Server Metrics ==========

@router.get("/servers/{server_id}")
async def get_server_metrics(
    server_id: str,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    interval: str = Query("1m"),
    limit: int = Query(60, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get metrics history for a server"""
    checker = PermissionChecker(current_user)

    # Check server ownership or admin
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE])

    if not from_date:
        from_date = datetime.utcnow() - timedelta(hours=1)
    if not to_date:
        to_date = datetime.utcnow()

    query = select(ServerMetric).where(
        and_(
            ServerMetric.server_id == server_id,
            ServerMetric.collected_at >= from_date,
            ServerMetric.collected_at <= to_date
        )
    ).order_by(desc(ServerMetric.collected_at))

    result = await db.execute(query)
    metrics = result.scalars().all()

    # If limit is specified and we have more metrics than limit, subsample evenly
    if limit and len(metrics) > limit:
        step = len(metrics) / limit
        metrics = [metrics[int(i * step)] for i in range(limit)]

    return {
        "metrics": [m.to_dict() for m in reversed(metrics)],
        "count": len(metrics),
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    }


@router.get("/servers/{server_id}/latest")
async def get_server_latest_metrics(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get latest metrics for a server"""
    checker = PermissionChecker(current_user)

    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE])

    result = await db.execute(
        select(ServerMetric).where(
            ServerMetric.server_id == server_id
        ).order_by(desc(ServerMetric.collected_at)).limit(1)
    )
    metric = result.scalar_one_or_none()

    if not metric:
        return {"metric": None}

    return {"metric": metric.to_dict()}


# ========== System Metrics ==========

@router.get("/system")
async def get_system_metrics(
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(60, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get system-level metrics history"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    if not from_date:
        from_date = datetime.utcnow() - timedelta(hours=1)
    if not to_date:
        to_date = datetime.utcnow()

    query = select(SystemMetric).where(
        and_(
            SystemMetric.collected_at >= from_date,
            SystemMetric.collected_at <= to_date
        )
    ).order_by(desc(SystemMetric.collected_at))

    result = await db.execute(query)
    metrics = result.scalars().all()

    # Subsample if exceeding limit
    if limit and len(metrics) > limit:
        step = len(metrics) / limit
        metrics = [metrics[int(i * step)] for i in range(limit)]

    return {
        "metrics": [m.to_dict() for m in reversed(metrics)],
        "count": len(metrics),
    }


@router.get("/system/latest")
async def get_latest_system_metrics(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get latest system metrics"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    result = await db.execute(
        select(SystemMetric).order_by(desc(SystemMetric.collected_at)).limit(1)
    )
    metric = result.scalar_one_or_none()

    return {"metric": metric.to_dict() if metric else None}


# ========== Alert Rules ==========

@router.get("/alerts/rules")
async def list_alert_rules(
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """List all alert rules"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))
    rules = result.scalars().all()

    return {"rules": [r.to_dict() for r in rules]}


@router.post("/alerts/rules")
async def create_alert_rule(
    data: AlertRuleCreate,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Create a new alert rule"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    import uuid

    rule = AlertRule(
        name=data.name,
        description=data.description,
        metric_type=data.metric_type,
        operator=data.operator,
        threshold=data.threshold,
        scope=data.scope,
        target_id=uuid.UUID(data.target_id) if data.target_id else None,
        duration_seconds=data.duration_seconds,
        cooldown_seconds=data.cooldown_seconds,
        notify_admin=data.notify_admin,
        notify_user=data.notify_user,
        email_enabled=data.email_enabled,
        webhook_url=data.webhook_url,
        created_by=current_user.id,
    )

    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return rule.to_dict()


@router.get("/alerts/rules/{rule_id}")
async def get_alert_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Get alert rule details"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    import uuid

    result = await db.execute(
        select(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    return rule.to_dict()


@router.put("/alerts/rules/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    data: AlertRuleUpdate,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Update an alert rule"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    import uuid

    result = await db.execute(
        select(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'target_id' and value:
            value = uuid.UUID(value)
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)

    return rule.to_dict()


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Delete an alert rule"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    import uuid

    result = await db.execute(
        select(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    await db.delete(rule)
    await db.commit()

    return {"message": "Alert rule deleted"}


# ========== Alert History ==========

@router.get("/alerts/history")
async def list_alert_history(
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """List alert history"""
    checker = PermissionChecker(current_user)
    is_admin = checker.is_admin()

    query = select(AlertHistory)

    if not is_admin:
        query = query.where(AlertHistory.user_id == current_user.id)

    if status:
        query = query.where(AlertHistory.status == status)

    query = query.order_by(desc(AlertHistory.fired_at))
    result = await db.execute(query)
    alerts = result.scalars().all()

    return {"alerts": [a.to_dict() for a in alerts]}


@router.post("/alerts/history/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    data: AlertAcknowledgeRequest,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Acknowledge an alert"""
    service = AlertService(db)
    alert = await service.acknowledge_alert(alert_id, str(current_user.id), data.notes)

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return alert.to_dict()


@router.post("/alerts/history/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Resolve an alert"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    service = AlertService(db)
    alert = await service.resolve_alert(alert_id)

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return alert.to_dict()


# ========== Health Checks ==========

@router.get("/health/servers/{server_id}")
async def get_server_health_checks(
    server_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get health check history for a server"""
    checker = PermissionChecker(current_user)

    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE])

    result = await db.execute(
        select(HealthCheck).where(
            HealthCheck.server_id == server_id
        ).order_by(desc(HealthCheck.checked_at)).limit(limit)
    )
    checks = result.scalars().all()

    return {
        "checks": [c.to_dict() for c in checks],
        "latest": checks[0].to_dict() if checks else None,
    }


@router.get("/health/summary")
async def get_health_summary(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get overall health summary"""
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.ADMIN_ACCESS, Permission.SERVERS_MANAGE])

    # Count by status
    result = await db.execute(
        select(HealthCheck.status, func.count(HealthCheck.id))
        .group_by(HealthCheck.status)
    )
    status_counts = {status: count for status, count in result.all()}

    # Latest checks per server
    from sqlalchemy import distinct
    result = await db.execute(
        select(HealthCheck)
        .distinct(HealthCheck.server_id)
        .order_by(HealthCheck.server_id, desc(HealthCheck.checked_at))
    )
    latest = result.scalars().all()

    return {
        "status_counts": status_counts,
        "latest_checks": [c.to_dict() for c in latest],
        "unhealthy_count": status_counts.get('unhealthy', 0),
        "unknown_count": status_counts.get('unknown', 0),
    }
