"""
Backup and restore service for Docker volumes.
"""

import os
import tarfile
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.volume_service import VolumeService


class BackupService:
    """Volume backup and restore management"""

    def __init__(self, db: AsyncSession, backup_path: str = "/app/backups"):
        self.db = db
        self.backup_path = backup_path
        os.makedirs(backup_path, exist_ok=True)

    async def create_backup(
        self, volume_name: str, user_id: str, description: str | None = None
    ) -> dict[str, Any]:
        """Create a tar.gz backup of a Docker volume"""
        from app.models.volume_backup import VolumeBackup

        # Verify volume exists
        volume_service = VolumeService()
        volume = await volume_service.get_volume(volume_name)
        if not volume:
            raise ValueError(f"Volume {volume_name} not found")

        # Generate backup filename
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%d_%H%M%S")
        filename = f"{volume_name}_{timestamp}_{backup_id[:8]}.tar.gz"
        filepath = os.path.join(self.backup_path, filename)

        # Create backup record
        backup = VolumeBackup(
            id=uuid.UUID(backup_id),
            volume_name=volume_name,
            user_id=uuid.UUID(user_id) if user_id else None,
            backup_path=filepath,
            status="in_progress",
            description=description,
        )
        self.db.add(backup)
        await self.db.commit()

        try:
            # Get volume mountpoint
            mountpoint = volume.get("mountpoint")
            if not mountpoint:
                # Fallback: construct path from volume name
                mountpoint = f"/var/lib/docker/volumes/{volume_name}/_data"

            # Create tar.gz archive
            with tarfile.open(filepath, "w:gz") as tar:
                tar.add(mountpoint, arcname=".")

            # Get file size
            size_bytes = os.path.getsize(filepath)

            # Update backup record
            backup.status = "completed"
            backup.size_bytes = size_bytes
            backup.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await self.db.commit()

            # Notify user if user_id is available
            if backup.user_id:
                from app.services.notification_service import NotificationService

                notif_service = NotificationService(self.db)
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes else "0 B"
                await notif_service.server_backup_completed(
                    user_id=backup.user_id, server_name=volume_name, backup_size=size_str
                )

            return {
                "id": backup_id,
                "volume_name": volume_name,
                "status": "completed",
                "size_bytes": size_bytes,
                "backup_path": filepath,
                "created_at": backup.created_at.isoformat(),
                "completed_at": backup.completed_at.isoformat(),
            }
        except Exception as e:
            backup.status = "failed"
            backup.error_message = str(e)
            await self.db.commit()
            raise

    async def list_backups(
        self, volume_name: str | None = None, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List backups, optionally filtered by volume or user"""
        from app.models.volume_backup import VolumeBackup

        query = select(VolumeBackup)

        if volume_name:
            query = query.where(VolumeBackup.volume_name == volume_name)

        if user_id:
            query = query.where(VolumeBackup.user_id == uuid.UUID(user_id))

        query = query.order_by(desc(VolumeBackup.created_at))

        result = await self.db.execute(query)
        backups = result.scalars().all()

        return [
            {
                "id": str(b.id),
                "volume_name": b.volume_name,
                "size_bytes": b.size_bytes,
                "status": b.status,
                "description": b.description,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "completed_at": b.completed_at.isoformat() if b.completed_at else None,
            }
            for b in backups
        ]

    async def get_backup(self, backup_id: str) -> dict[str, Any] | None:
        """Get backup details"""
        from app.models.volume_backup import VolumeBackup

        result = await self.db.execute(
            select(VolumeBackup).where(VolumeBackup.id == uuid.UUID(backup_id))
        )
        backup = result.scalar_one_or_none()

        if not backup:
            return None

        return {
            "id": str(backup.id),
            "volume_name": backup.volume_name,
            "size_bytes": backup.size_bytes,
            "status": backup.status,
            "backup_path": backup.backup_path,
            "description": backup.description,
            "error_message": backup.error_message,
            "created_at": backup.created_at.isoformat() if backup.created_at else None,
            "completed_at": backup.completed_at.isoformat() if backup.completed_at else None,
        }

    async def restore_backup(
        self, backup_id: str, target_volume_name: str | None = None
    ) -> dict[str, Any]:
        """Restore a backup to a volume"""
        from app.models.volume_backup import VolumeBackup

        result = await self.db.execute(
            select(VolumeBackup).where(VolumeBackup.id == uuid.UUID(backup_id))
        )
        backup = result.scalar_one_or_none()

        if not backup:
            raise ValueError(f"Backup {backup_id} not found")

        if backup.status != "completed":
            raise ValueError(f"Cannot restore backup with status: {backup.status}")

        if not os.path.exists(backup.backup_path):
            raise ValueError(f"Backup file not found: {backup.backup_path}")

        volume_name = target_volume_name or backup.volume_name

        # Get or create volume
        volume_service = VolumeService()
        volume = await volume_service.get_volume(volume_name)

        if not volume:
            # Create volume
            container_client = await volume_service.get_container_client()
            await container_client.client.volumes.create(
                name=volume_name, labels={"nukelab.managed": "true"}
            )

        # Get mountpoint
        mountpoint = (
            volume.get("mountpoint") if volume else f"/var/lib/docker/volumes/{volume_name}/_data"
        )

        # Ensure mountpoint exists
        os.makedirs(mountpoint, exist_ok=True)

        # Extract backup
        with tarfile.open(backup.backup_path, "r:gz") as tar:
            tar.extractall(path=mountpoint, filter="data")

        return {
            "backup_id": backup_id,
            "volume_name": volume_name,
            "status": "restored",
            "restored_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        }

    async def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup"""
        from app.models.volume_backup import VolumeBackup

        result = await self.db.execute(
            select(VolumeBackup).where(VolumeBackup.id == uuid.UUID(backup_id))
        )
        backup = result.scalar_one_or_none()

        if not backup:
            return False

        # Delete file if exists
        if backup.backup_path and os.path.exists(backup.backup_path):
            os.remove(backup.backup_path)

        await self.db.delete(backup)
        await self.db.commit()

        return True

    async def apply_retention_policy(self):
        """Apply backup retention policy: 7 daily, 4 weekly, 12 monthly"""
        from app.models.volume_backup import VolumeBackup

        result = await self.db.execute(select(VolumeBackup).order_by(desc(VolumeBackup.created_at)))
        all_backups = result.scalars().all()

        # Group backups by volume
        by_volume = {}
        for backup in all_backups:
            if backup.volume_name not in by_volume:
                by_volume[backup.volume_name] = []
            by_volume[backup.volume_name].append(backup)

        deleted_count = 0

        for _volume_name, backups in by_volume.items():
            # Keep 7 most recent daily
            daily_keep = backups[:7]

            # Keep 4 weekly (every 7th from remaining)
            remaining = backups[7:]
            weekly_keep = remaining[::7][:4]

            # Keep 12 monthly (every 30th from remaining after weekly)
            after_weekly = [b for b in remaining if b not in weekly_keep]
            monthly_keep = after_weekly[::30][:12]

            to_keep = set(daily_keep + weekly_keep + monthly_keep)
            to_delete = [b for b in backups if b not in to_keep]

            for backup in to_delete:
                if backup.backup_path and os.path.exists(backup.backup_path):
                    os.remove(backup.backup_path)
                await self.db.delete(backup)
                deleted_count += 1

        await self.db.commit()
        return {"deleted": deleted_count, "retained": len(all_backups) - deleted_count}
