"""
Volume API endpoints.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.auth import get_current_user
from app.core.filesystem import secure_path
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import PermissionChecker, require_permissions
from app.models.user import User
from app.services.notification_service import NotificationService
from app.services.quota_service import QuotaService
from app.services.volume_access_service import VolumeAccessService
from app.services.volume_service import VolumeService

router = APIRouter()


class VolumeCreateRequest(BaseModel):
    display_name: str
    description: str | None = None
    max_size_bytes: int | None = None


class VolumeUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    visibility: str | None = None
    max_size_bytes: int | None = None
    status: str | None = None


class VolumeResponse(BaseModel):
    id: str
    name: str
    display_name: str
    owner_id: str
    visibility: str
    size_bytes: int
    max_size_bytes: int | None
    status: str
    server_count: int
    description: str | None
    created_at: str
    updated_at: str


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_volume(
    request: VolumeCreateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new volume."""
    # Check disk quota before creating
    quota_service = QuotaService(db)
    quota_check = await quota_service.check_volume_creation_allowed(
        user_id=str(current_user.id), requested_size_bytes=request.max_size_bytes
    )
    if not quota_check["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=quota_check["reason"]
        )

    volume_service = VolumeService(db)

    # Generate unique volume name
    import uuid

    volume_name = f"nukelab-vol-{current_user.username}-{uuid.uuid4().hex[:8]}"

    volume = await volume_service.create_volume(
        name=volume_name,
        display_name=request.display_name,
        owner_id=str(current_user.id),
        max_size_bytes=request.max_size_bytes,
        description=request.description,
    )

    # Notify user
    notif_service = NotificationService(db)
    await notif_service.volume_created(
        user_id=current_user.id, volume_name=request.display_name or volume_name
    )

    return volume.to_dict()


@router.get("/")
async def list_volumes(
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_READ_OWN, Permission.VOLUMES_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """List volumes accessible to user."""
    volume_service = VolumeService(db)
    volumes = await volume_service.list_volumes(str(current_user.id))

    result = []
    for v in volumes:
        data = v.to_dict()
        data["workspace_count"] = len(v.workspace_associations) if v.workspace_associations else 0
        result.append(data)
    return {"volumes": result}


@router.get("/{volume_id}")
async def get_volume(
    volume_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_READ_OWN, Permission.VOLUMES_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get volume details."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    # Check access
    if not await volume_access.can_access_volume(volume_id, str(current_user.id), "read_only"):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    return volume.to_dict()


@router.put("/{volume_id}")
async def update_volume(
    volume_id: str,
    request: VolumeUpdateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Update volume. Only owner can update."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_manage_volume(volume_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    # Validate max_size_bytes cannot be set below current size
    try:
        volume_service.validate_max_size(volume, request.max_size_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Prevent destructive status changes on volumes mounted by running servers
    if request.status and request.status in ("archived", "deleting"):
        from sqlalchemy import func

        from app.models.server import Server
        from app.models.server_volume import ServerVolume

        mount_result = await db.execute(
            select(func.count())
            .select_from(ServerVolume)
            .join(Server, ServerVolume.server_id == Server.id)
            .where(
                ServerVolume.volume_id == volume.id,
                Server.status.in_(["running", "healthy"]),
            )
        )
        active_mounts = mount_result.scalar() or 0
        if active_mounts > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot change status to '{request.status}': "
                    f"volume is mounted by {active_mounts} running server(s). "
                    f"Stop the server(s) first."
                ),
            )

    updated = await volume_service.update_volume(
        volume_id=volume_id,
        display_name=request.display_name,
        description=request.description,
        visibility=request.visibility,
        max_size_bytes=request.max_size_bytes,
        status=request.status,
    )

    return updated.to_dict()


@router.delete("/{volume_id}")
async def delete_volume(
    volume_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Delete volume. Only owner can delete."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_manage_volume(volume_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    # Get volume name before deletion for notification
    volume_name = volume.display_name or volume.name

    try:
        success = await volume_service.delete_volume(volume_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete volume")
    except ValueError:
        logger.exception("Volume deletion failed")
        raise HTTPException(status_code=400, detail="Failed to delete volume. Please try again.")

    # Notify user
    notif_service = NotificationService(db)
    await notif_service.volume_deleted(user_id=volume.owner_id, volume_name=volume_name)

    return {"message": "Volume deleted", "volume_id": volume_id}


@router.post("/{volume_id}/refresh-size")
async def refresh_volume_size(
    volume_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Refresh volume size from filesystem."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_access_volume(volume_id, str(current_user.id), "read_only"):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    size = await volume_service.update_volume_size(volume_id)
    return {"volume_id": volume_id, "size_bytes": size}


# =============================================================================
# Volume File Browser
# =============================================================================

import mimetypes
import os
from pathlib import Path

VOLUME_STORAGE_PATH = os.environ.get("VOLUME_STORAGE_PATH", "/var/lib/docker/volumes")


def _get_volume_base_path(volume_name: str) -> Path:
    """Get the base filesystem path for a volume."""
    return Path(VOLUME_STORAGE_PATH) / volume_name / "_data"


@router.get("/{volume_id}/files")
async def list_volume_files(
    volume_id: str,
    path: str = "",
    search: str | None = None,
    sort_by: str = "name",  # name, size, modified
    sort_order: str = "asc",  # asc, desc
    page: int = 1,
    page_size: int = 100,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_READ_OWN, Permission.VOLUMES_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """List files and directories in a volume with pagination, search, and sorting."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_access_volume(volume_id, str(current_user.id), "read_only"):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    try:
        base_path = _get_volume_base_path(volume.name)
        target_path = secure_path(base_path, path)

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if target_path.is_file():
            stat = target_path.stat()
            return {
                "type": "file",
                "name": target_path.name,
                "path": path,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "items": [],
                "total": 1,
                "page": 1,
                "page_size": 1,
                "total_pages": 1,
            }

        # Collect all items
        items = []
        for item in target_path.iterdir():
            try:
                stat = item.stat()
                items.append(
                    {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else None,
                        "modified": stat.st_mtime,
                    }
                )
            except (OSError, PermissionError):
                continue

        # Search filter
        if search:
            search_lower = search.lower()
            items = [item for item in items if search_lower in item["name"].lower()]

        # Sorting
        reverse = sort_order.lower() == "desc"
        if sort_by == "name":
            items.sort(
                key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()),
                reverse=reverse,
            )
        elif sort_by == "size":
            items.sort(key=lambda x: (x["size"] or 0, x["name"].lower()), reverse=reverse)
        elif sort_by == "modified":
            items.sort(key=lambda x: (x["modified"], x["name"].lower()), reverse=reverse)
        else:
            # Default: directories first, then alphabetically
            items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))

        # Pagination
        total = len(items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]

        return {
            "type": "directory",
            "path": path,
            "items": paginated_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Volume file listing failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list files. Please try again or contact support.",
        )


@router.delete("/{volume_id}/files")
async def delete_volume_file(
    volume_id: str,
    path: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file or directory in a volume."""
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_access_volume(volume_id, str(current_user.id), "read_write"):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    try:
        base_path = _get_volume_base_path(volume.name)
        target_path = secure_path(base_path, path)

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        # Safety: don't allow deleting the root of the volume
        if target_path == base_path.resolve():
            raise HTTPException(status_code=403, detail="Cannot delete volume root")

        if target_path.is_dir():
            import shutil

            shutil.rmtree(target_path)
        else:
            target_path.unlink()

        return {"message": "Deleted", "path": path}

    except HTTPException:
        raise
    except OSError as e:
        if e.errno == 30:  # Read-only file system
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Volume is read-only. Cannot modify files.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file or directory.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file or directory.",
        )


@router.get("/{volume_id}/download")
async def download_volume_file(
    volume_id: str,
    path: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.VOLUMES_READ_OWN, Permission.VOLUMES_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Download a file from a volume."""
    from fastapi.responses import FileResponse

    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)

    volume = await volume_service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    if not await volume_access.can_access_volume(volume_id, str(current_user.id), "read_only"):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)

    try:
        base_path = _get_volume_base_path(volume.name)
        target_path = secure_path(base_path, path)

        if not target_path.exists() or target_path.is_dir():
            raise HTTPException(status_code=404, detail="File not found")

        media_type, _ = mimetypes.guess_type(str(target_path))

        return FileResponse(
            path=str(target_path),
            filename=target_path.name,
            media_type=media_type or "application/octet-stream",
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Volume file download failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download file. Please try again or contact support.",
        )
