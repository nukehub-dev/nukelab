"""
Usage analytics service for aggregating platform metrics.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.dialects.postgresql import INTERVAL

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.user import User
from app.models.credit_transaction import CreditTransaction


class AnalyticsService:
    """Usage analytics and trends"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_usage(
        self,
        user_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get usage trends for a user over time"""
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get daily metrics aggregation
        day_trunc = func.date_trunc('day', ServerMetric.collected_at)
        result = await self.db.execute(
            select(
                day_trunc.label('day'),
                func.avg(ServerMetric.cpu_percent).label('avg_cpu'),
                func.max(ServerMetric.cpu_percent).label('peak_cpu'),
                func.avg(ServerMetric.memory_percent).label('avg_memory'),
                func.max(ServerMetric.memory_percent).label('peak_memory'),
                func.avg(ServerMetric.network_rx_bytes).label('avg_network_rx'),
                func.avg(ServerMetric.network_tx_bytes).label('avg_network_tx'),
                func.avg(ServerMetric.disk_read_bytes).label('avg_disk_read'),
                func.avg(ServerMetric.disk_write_bytes).label('avg_disk_write'),
                func.avg(ServerMetric.gpu_percent).label('avg_gpu'),
                func.max(ServerMetric.gpu_percent).label('peak_gpu'),
                func.count().label('data_points')
            ).join(
                Server, ServerMetric.server_id == Server.id
            ).where(
                and_(
                    Server.user_id == user_id,
                    ServerMetric.collected_at >= since
                )
            ).group_by(
                day_trunc
            ).order_by(
                day_trunc
            )
        )
        
        daily_data = result.all()
        
        # Get total cost
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= since
                )
            )
        )
        total_cost = abs(result.scalar() or 0)
        
        # Get cost per server breakdown
        result = await self.db.execute(
            select(
                Server.id,
                Server.name,
                func.sum(CreditTransaction.amount).label('cost')
            ).join(
                CreditTransaction, Server.id == CreditTransaction.server_id
            ).where(
                and_(
                    Server.user_id == user_id,
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= since
                )
            ).group_by(
                Server.id, Server.name
            ).order_by(func.sum(CreditTransaction.amount).asc())
        )
        
        server_costs = result.all()
        
        # Get peak usage stats
        result = await self.db.execute(
            select(
                func.max(ServerMetric.cpu_percent).label('peak_cpu'),
                func.max(ServerMetric.memory_percent).label('peak_memory'),
                func.max(ServerMetric.gpu_percent).label('peak_gpu'),
                func.avg(ServerMetric.cpu_percent).label('overall_avg_cpu'),
                func.avg(ServerMetric.memory_percent).label('overall_avg_memory'),
            ).join(
                Server, ServerMetric.server_id == Server.id
            ).where(
                and_(
                    Server.user_id == user_id,
                    ServerMetric.collected_at >= since
                )
            )
        )
        
        peak_stats = result.one_or_none()
        
        # Get previous period for comparison
        prev_since = since - timedelta(days=days)
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= prev_since,
                    CreditTransaction.created_at < since
                )
            )
        )
        prev_cost = abs(result.scalar() or 0)
        
        # Calculate cost trend
        cost_trend = 0
        if prev_cost > 0:
            cost_trend = ((total_cost - prev_cost) / prev_cost) * 100
        elif total_cost > 0:
            cost_trend = 100
        
        return {
            "user_id": user_id,
            "period_days": days,
            "daily_usage": [
                {
                    "date": day.isoformat() if day else None,
                    "avg_cpu": float(avg_cpu or 0),
                    "peak_cpu": float(peak_cpu or 0),
                    "avg_memory": float(avg_memory or 0),
                    "peak_memory": float(peak_memory or 0),
                    "avg_network_rx": float(avg_network_rx or 0),
                    "avg_network_tx": float(avg_network_tx or 0),
                    "avg_disk_read": float(avg_disk_read or 0),
                    "avg_disk_write": float(avg_disk_write or 0),
                    "avg_gpu": float(avg_gpu or 0) if avg_gpu else 0,
                    "peak_gpu": float(peak_gpu or 0) if peak_gpu else 0,
                    "data_points": data_points,
                }
                for day, avg_cpu, peak_cpu, avg_memory, peak_memory, avg_network_rx, avg_network_tx, avg_disk_read, avg_disk_write, avg_gpu, peak_gpu, data_points in daily_data
            ],
            "total_cost": total_cost,
            "prev_cost": prev_cost,
            "cost_trend": round(cost_trend, 1),
            "server_breakdown": [
                {
                    "server_id": str(sid),
                    "server_name": name or "Unnamed Server",
                    "cost": abs(int(cost or 0)),
                }
                for sid, name, cost in server_costs
            ],
            "peak_stats": {
                "peak_cpu": float(peak_stats.peak_cpu or 0) if peak_stats else 0,
                "peak_memory": float(peak_stats.peak_memory or 0) if peak_stats else 0,
                "peak_gpu": float(peak_stats.peak_gpu or 0) if peak_stats and peak_stats.peak_gpu else 0,
                "overall_avg_cpu": float(peak_stats.overall_avg_cpu or 0) if peak_stats else 0,
                "overall_avg_memory": float(peak_stats.overall_avg_memory or 0) if peak_stats else 0,
            } if peak_stats else {
                "peak_cpu": 0,
                "peak_memory": 0,
                "peak_gpu": 0,
                "overall_avg_cpu": 0,
                "overall_avg_memory": 0,
            },
            "active_days": len(daily_data),
        }
    
    async def get_global_usage(self, days: int = 30) -> Dict[str, Any]:
        """Get platform-wide usage statistics"""
        since = datetime.utcnow() - timedelta(days=days)
        
        # Active servers over time
        day_trunc = func.date_trunc('day', Server.created_at)
        result = await self.db.execute(
            select(
                day_trunc.label('day'),
                func.count().label('count')
            ).where(
                Server.created_at >= since
            ).group_by(
                day_trunc
            ).order_by(
                day_trunc
            )
        )
        server_creation = result.all()
        
        # Total credits consumed
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= since
                )
            )
        )
        total_credits = abs(result.scalar() or 0)
        
        # Active users
        result = await self.db.execute(
            select(func.count(func.distinct(Server.user_id))).where(
                Server.created_at >= since
            )
        )
        active_users = result.scalar() or 0
        
        return {
            "period_days": days,
            "server_creation_by_day": [
                {
                    "date": day.isoformat() if day else None,
                    "count": count,
                }
                for day, count in server_creation
            ],
            "total_credits_consumed": total_credits,
            "active_users": active_users,
        }
    
    async def get_top_consumers(self, days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top credit consumers"""
        since = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(
                User.id,
                User.username,
                func.sum(CreditTransaction.amount).label('total_consumed')
            ).join(
                CreditTransaction, User.id == CreditTransaction.user_id
            ).where(
                and_(
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= since
                )
            ).group_by(
                User.id, User.username
            ).order_by(
                func.sum(CreditTransaction.amount).asc()
            ).limit(limit)
        )
        
        consumers = result.all()
        
        return [
            {
                "user_id": str(user_id),
                "username": username,
                "credits_consumed": abs(int(total_consumed or 0)),
            }
            for user_id, username, total_consumed in consumers
        ]
    
    async def get_environment_usage(self) -> List[Dict[str, Any]]:
        """Get usage by environment"""
        from app.models.environment_template import EnvironmentTemplate
        
        result = await self.db.execute(
            select(
                EnvironmentTemplate.id,
                EnvironmentTemplate.name,
                func.count(Server.id).label('server_count')
            ).outerjoin(
                Server, Server.environment_id == EnvironmentTemplate.id
            ).group_by(
                EnvironmentTemplate.id, EnvironmentTemplate.name
            ).order_by(
                func.count(Server.id).desc()
            )
        )
        
        environments = result.all()
        
        return [
            {
                "id": str(env_id),
                "name": name,
                "server_count": server_count,
            }
            for env_id, name, server_count in environments
        ]
    
    async def get_plan_usage(self) -> List[Dict[str, Any]]:
        """Get usage by plan"""
        from app.models.server_plan import ServerPlan
        
        result = await self.db.execute(
            select(
                ServerPlan.id,
                ServerPlan.name,
                func.count(Server.id).label('server_count')
            ).outerjoin(
                Server, Server.plan_id == ServerPlan.id
            ).group_by(
                ServerPlan.id, ServerPlan.name
            ).order_by(
                func.count(Server.id).desc()
            )
        )
        
        plans = result.all()
        
        return [
            {
                "id": str(plan_id),
                "name": name,
                "server_count": server_count,
            }
            for plan_id, name, server_count in plans
        ]
