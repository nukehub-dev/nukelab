"""
Usage analytics service for aggregating platform metrics.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text, case
from sqlalchemy.dialects.postgresql import INTERVAL

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.user import User
from app.models.credit_transaction import CreditTransaction
from app.models.volume import Volume
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember


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
        
        # Get daily cost
        day_trunc_tx = func.date_trunc('day', CreditTransaction.created_at)
        result = await self.db.execute(
            select(
                day_trunc_tx.label('day'),
                func.sum(CreditTransaction.amount).label('daily_cost')
            ).where(
                and_(
                    CreditTransaction.user_id == user_id,
                    CreditTransaction.type == "server_usage",
                    CreditTransaction.created_at >= since
                )
            ).group_by(
                day_trunc_tx
            ).order_by(
                day_trunc_tx
            )
        )
        daily_costs = {day.isoformat() if day else None: abs(int(cost or 0)) for day, cost in result.all()}
        
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
                    "daily_cost": daily_costs.get(day.isoformat() if day else None, 0),
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
        
        # Active users (users who created servers in period)
        result = await self.db.execute(
            select(func.count(func.distinct(Server.user_id))).where(
                Server.created_at >= since
            )
        )
        active_users = result.scalar() or 0
        
        # Total users
        result = await self.db.execute(select(func.count()).select_from(User))
        total_users = result.scalar() or 0
        
        # New users in period
        result = await self.db.execute(
            select(func.count()).select_from(User).where(User.created_at >= since)
        )
        new_users = result.scalar() or 0
        
        # Total servers
        result = await self.db.execute(select(func.count()).select_from(Server))
        total_servers = result.scalar() or 0
        
        # Running servers
        result = await self.db.execute(
            select(func.count()).where(Server.status == "running")
        )
        running_servers = result.scalar() or 0
        
        # Server status breakdown
        result = await self.db.execute(
            select(Server.status, func.count()).group_by(Server.status)
        )
        status_breakdown = {status: count for status, count in result.all()}
        
        # Average platform CPU
        result = await self.db.execute(
            select(func.avg(ServerMetric.cpu_percent)).where(
                ServerMetric.collected_at >= since
            )
        )
        avg_platform_cpu = float(result.scalar() or 0)
        
        # Average platform memory
        result = await self.db.execute(
            select(func.avg(ServerMetric.memory_percent)).where(
                ServerMetric.collected_at >= since
            )
        )
        avg_platform_memory = float(result.scalar() or 0)
        
        # Total runtime hours (approximate from started_at / stopped_at)
        result = await self.db.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(
                            func.extract('epoch', Server.stopped_at - Server.started_at),
                            func.extract('epoch', func.now() - Server.started_at)
                        ) / 3600
                    ),
                    0
                )
            ).where(Server.started_at.isnot(None))
        )
        total_runtime_hours = float(result.scalar() or 0)
        
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
            "total_users": total_users,
            "new_users": new_users,
            "total_servers": total_servers,
            "running_servers": running_servers,
            "server_status_breakdown": status_breakdown,
            "avg_platform_cpu": round(avg_platform_cpu, 1),
            "avg_platform_memory": round(avg_platform_memory, 1),
            "total_runtime_hours": round(total_runtime_hours, 1),
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
    
    async def get_credit_flow(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily credit flow (consumed vs granted) over time"""
        since = datetime.utcnow() - timedelta(days=days)
        day_trunc = func.date_trunc('day', CreditTransaction.created_at)
        
        result = await self.db.execute(
            select(
                day_trunc.label('day'),
                func.sum(
                    case(
                        (CreditTransaction.amount < 0, CreditTransaction.amount),
                        else_=0
                    )
                ).label('consumed'),
                func.sum(
                    case(
                        (CreditTransaction.amount > 0, CreditTransaction.amount),
                        else_=0
                    )
                ).label('granted')
            ).where(
                CreditTransaction.created_at >= since
            ).group_by(
                day_trunc
            ).order_by(
                day_trunc
            )
        )
        
        rows = result.all()
        return [
            {
                "date": day.isoformat() if day else None,
                "credits_consumed": abs(int(consumed or 0)),
                "credits_granted": int(granted or 0),
            }
            for day, consumed, granted in rows
        ]
    
    async def get_user_growth(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily new user signups over time"""
        since = datetime.utcnow() - timedelta(days=days)
        day_trunc = func.date_trunc('day', User.created_at)
        
        result = await self.db.execute(
            select(
                day_trunc.label('day'),
                func.count().label('count')
            ).where(
                User.created_at >= since
            ).group_by(
                day_trunc
            ).order_by(
                day_trunc
            )
        )
        
        rows = result.all()
        return [
            {
                "date": day.isoformat() if day else None,
                "count": count,
            }
            for day, count in rows
        ]
    
    async def get_platform_metrics(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily aggregated platform-wide resource usage"""
        since = datetime.utcnow() - timedelta(days=days)
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
                func.count().label('data_points')
            ).where(
                ServerMetric.collected_at >= since
            ).group_by(
                day_trunc
            ).order_by(
                day_trunc
            )
        )
        
        rows = result.all()
        return [
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
                "data_points": data_points,
            }
            for day, avg_cpu, peak_cpu, avg_memory, peak_memory, avg_network_rx, avg_network_tx, avg_disk_read, avg_disk_write, data_points in rows
        ]
    
    async def get_volume_analytics(self) -> Dict[str, Any]:
        """Get storage/volume analytics snapshot"""
        # Total volumes
        result = await self.db.execute(select(func.count()).select_from(Volume))
        total_volumes = result.scalar() or 0
        
        # Storage used and capacity
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(Volume.size_bytes), 0),
                func.coalesce(func.sum(Volume.max_size_bytes), 0)
            )
        )
        size_row = result.one_or_none()
        total_size_bytes = int(size_row[0] if size_row else 0)
        total_capacity_bytes = int(size_row[1] if size_row else 0)
        
        total_storage_used_gb = round(total_size_bytes / (1024 ** 3), 2)
        total_storage_capacity_gb = round(total_capacity_bytes / (1024 ** 3), 2) if total_capacity_bytes else 0
        
        storage_utilization_percent = 0
        if total_capacity_bytes > 0:
            storage_utilization_percent = round((total_size_bytes / total_capacity_bytes) * 100, 1)
        
        # By visibility
        result = await self.db.execute(
            select(Volume.visibility, func.count()).group_by(Volume.visibility)
        )
        volumes_by_visibility = [
            {"visibility": vis or "unknown", "count": count}
            for vis, count in result.all()
        ]
        
        # By status
        result = await self.db.execute(
            select(Volume.status, func.count()).group_by(Volume.status)
        )
        volumes_by_status = [
            {"status": stat or "unknown", "count": count}
            for stat, count in result.all()
        ]
        
        return {
            "total_volumes": total_volumes,
            "total_storage_used_gb": total_storage_used_gb,
            "total_storage_capacity_gb": total_storage_capacity_gb,
            "storage_utilization_percent": storage_utilization_percent,
            "volumes_by_visibility": volumes_by_visibility,
            "volumes_by_status": volumes_by_status,
        }
    
    async def get_workspace_analytics(self) -> Dict[str, Any]:
        """Get workspace collaboration analytics snapshot"""
        # Total workspaces
        result = await self.db.execute(select(func.count()).select_from(SharedWorkspace))
        total_workspaces = result.scalar() or 0
        
        # Total members
        result = await self.db.execute(select(func.count()).select_from(WorkspaceMember))
        total_members = result.scalar() or 0
        
        # Average members per workspace
        avg_members = 0
        if total_workspaces > 0:
            avg_members = round(total_members / total_workspaces, 1)
        
        # Workspace adoption: users who own or belong to a workspace / total users
        result = await self.db.execute(
            select(func.count(func.distinct(WorkspaceMember.user_id)))
        )
        workspace_users = result.scalar() or 0
        
        result = await self.db.execute(
            select(func.count(func.distinct(SharedWorkspace.owner_id)))
        )
        workspace_owners = result.scalar() or 0
        
        total_workspace_users = len(set())  # Can't easily union in SQLAlchemy without subquery
        # Better: use a subquery approach
        result = await self.db.execute(
            select(func.count(func.distinct(WorkspaceMember.user_id))).union(
                select(func.count(func.distinct(SharedWorkspace.owner_id)))
            )
        )
        # Union gives separate rows; we need a proper count
        # Let's use a subquery
        result = await self.db.execute(
            select(func.count()).select_from(
                select(WorkspaceMember.user_id).union(
                    select(SharedWorkspace.owner_id)
                ).subquery()
            )
        )
        unique_workspace_users = result.scalar() or 0
        
        result = await self.db.execute(select(func.count()).select_from(User))
        total_users = result.scalar() or 0
        
        adoption_rate = 0
        if total_users > 0:
            adoption_rate = round((unique_workspace_users / total_users) * 100, 1)
        
        return {
            "total_workspaces": total_workspaces,
            "total_members": total_members,
            "avg_members_per_workspace": avg_members,
            "workspace_adoption_rate": adoption_rate,
            "unique_workspace_users": unique_workspace_users,
            "total_users": total_users,
        }
    
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
