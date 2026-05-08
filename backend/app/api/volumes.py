"""
Volume API endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.volume_service import VolumeService
from app.services.backup_service import BackupService

router = APIRouter()


@router.get("/")
async def list_volumes(
    current_user: User = Depends(get_current_user),
):
    """List volumes. Users see own volumes, admins see all."""
    service = VolumeService()
    
    checker = PermissionChecker(current_user)
    if checker.is_admin():
        volumes = await service.list_volumes()
    else:
        volumes = await service.list_volumes(user_id=str(current_user.id))
    
    return {"volumes": volumes}


@router.get("/{name}")
async def get_volume(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """Get volume details."""
    service = VolumeService()
    
    volume = await service.get_volume(name)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")
    
    # Check ownership
    labels = volume.get('labels', {})
    volume_user_id = labels.get('nukelab.user.id')
    
    if volume_user_id and str(volume_user_id) != str(current_user.id):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN)
    
    return volume


@router.delete("/{name}")
async def delete_volume(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a volume. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN)
    
    service = VolumeService()
    
    volume = await service.get_volume(name)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")
    
    success = await service.delete_volume(name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete volume"
        )
    
    return {"message": "Volume deleted", "name": name}


# ========== Backup Endpoints ==========

@router.post("/{name}/backup")
async def backup_volume(
    name: str,
    description: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a backup of a volume."""
    service = BackupService(db)
    
    try:
        result = await service.create_backup(
            volume_name=name,
            user_id=str(current_user.id),
            description=description
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup: {str(e)}"
        )


@router.get("/{name}/backups")
async def list_volume_backups(
    name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List backups for a specific volume."""
    service = BackupService(db)
    backups = await service.list_backups(volume_name=name)
    return {"backups": backups}


@router.get("/backups/{backup_id}")
async def get_backup(
    backup_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get backup details."""
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    return backup


@router.post("/backups/{backup_id}/restore")
async def restore_backup(
    backup_id: str,
    target_volume_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restore a backup to a volume."""
    service = BackupService(db)
    
    try:
        result = await service.restore_backup(backup_id, target_volume_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup: {str(e)}"
        )


@router.delete("/backups/{backup_id}")
async def delete_backup(
    backup_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a backup. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN)
    
    service = BackupService(db)
    success = await service.delete_backup(backup_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    return {"message": "Backup deleted", "backup_id": backup_id}


@router.get("/backups/all")
async def list_all_backups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all backups. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN)
    
    service = BackupService(db)
    backups = await service.list_backups()
    return {"backups": backups}
