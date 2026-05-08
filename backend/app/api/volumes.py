"""
Volume API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.volume_service import VolumeService

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
