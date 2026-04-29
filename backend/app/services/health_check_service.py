from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.docker.client import get_fresh_docker_client
from app.models.health_check import HealthCheck
from app.models.server import Server


class HealthCheckService:
    """Perform and track container health checks"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_all_containers(self):
        """Check health of all running containers"""
        result = await self.db.execute(
            select(Server).where(Server.status == "running")
        )
        servers = result.scalars().all()

        for server in servers:
            if not server.container_id:
                continue

            try:
                await self._check_container(server)
            except Exception as e:
                print(f"Health check failed for {server.id}: {e}")

    async def _check_container(self, server: Server):
        """Check health of a single container"""
        docker = None
        try:
            docker = await get_fresh_docker_client()
            container = await docker.client.containers.get(server.container_id)
            info = await container.show()
            state = info.get('State', {})

            health = state.get('Health', {})
            health_status = health.get('Status', 'unknown')

            if health_status == 'unknown':
                if state.get('Running'):
                    health_status = 'healthy'
                else:
                    health_status = 'unhealthy'

            log = health.get('Log', [])
            last_check = log[-1] if log else {}

            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id,
                status=health_status,
                exit_code=last_check.get('ExitCode'),
                output=(last_check.get('Output', '') or '')[:1000],
            )

            # Track consecutive failures
            if health_status == 'unhealthy':
                last_check_result = await self.db.execute(
                    select(HealthCheck).where(
                        HealthCheck.server_id == server.id
                    ).order_by(HealthCheck.checked_at.desc()).limit(1)
                )
                last = last_check_result.scalar_one_or_none()
                if last and last.status == 'unhealthy':
                    health_check.consecutive_failures = last.consecutive_failures + 1
                else:
                    health_check.consecutive_failures = 1
            else:
                health_check.last_success_at = datetime.utcnow()

            self.db.add(health_check)
            await self.db.commit()

            # Auto-restart if too many failures
            if health_check.consecutive_failures >= 3:
                await self._auto_restart(server)

        except Exception as e:
            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id or '',
                status='unknown',
                output=str(e)[:1000],
            )
            self.db.add(health_check)
            await self.db.commit()
        finally:
            if docker and docker.client:
                try:
                    await docker.client.close()
                except Exception:
                    pass

    async def _auto_restart(self, server: Server):
        """Auto-restart a failed container"""
        print(f"Auto-restarting server {server.id} after consecutive failures")
        # TODO: Implement auto-restart with rate limiting
        # This would call the spawner restart logic
