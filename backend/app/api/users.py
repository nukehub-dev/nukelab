"""
User API endpoints with RBAC enforcement.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.core.security import get_user_permissions
from app.dependencies import require_permissions, PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import UserService
from app.services.activity_service import ActivityService
from app.config import settings

router = APIRouter()


# Request/Response Models
class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6)
    role: str = Field(default="user")
    first_name: Optional[str] = Field(default=None, max_length=255)
    last_name: Optional[str] = Field(default=None, max_length=255)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    credits: int = Field(default=500, ge=0)


class UserUpdateRequest(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=255)
    last_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    role: Optional[str] = None
    profile: Optional[dict] = None
    preferences: Optional[dict] = None
    nuke_balance: Optional[int] = None
    profile_visibility: Optional[str] = Field(default=None, pattern=r"^(private|public)$")


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    display_name: str
    avatar_url: str
    role: str
    permissions: List[str]
    nuke_balance: int
    daily_allowance: int
    profile: dict
    preferences: dict
    profile_visibility: str
    oauth_provider: Optional[str] = None
    is_active: bool
    is_verified: bool
    last_login: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    login_count: int


class UserListResponse(BaseModel):
    users: List[UserResponse]
    pagination: dict


class DisableUserRequest(BaseModel):
    disabled: bool = True
    reason: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


def serialize_user(user: User) -> dict:
    """Serialize user to dict"""
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name,
        "avatar_url": user.get_avatar_url(),
        "role": user.role,
        "permissions": get_user_permissions(user),
        "nuke_balance": user.nuke_balance,
        "profile": user.profile or {},
        "preferences": user.preferences or {},
        "profile_visibility": user.profile_visibility or "private",
        "oauth_provider": user.oauth_provider,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "login_count": user.login_count,
        "daily_allowance": user.daily_allowance,
    }


class DiscoverUserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    avatar_url: str


class DiscoverUserListResponse(BaseModel):
    users: List[DiscoverUserResponse]


# ========== Public Discovery Endpoints ==========

@router.get("/discover", response_model=DiscoverUserListResponse)
async def discover_users(
    search: Optional[str] = Query(None, description="Search username/display name"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Discover public users for collaboration. Any authenticated user can access.
    
    Returns only users who have set their profile_visibility to 'public'.
    Excludes sensitive fields like email, role, and balance.
    """
    service = UserService(db)
    users = await service.discover_users(search=search, limit=limit)
    
    return {
        "users": [
            {
                "id": str(u.id),
                "username": u.username,
                "display_name": u.display_name,
                "avatar_url": u.get_avatar_url(),
            }
            for u in users
        ]
    }


# ========== User CRUD Endpoints ==========

# ========== Profile Endpoints (Current User) ==========

@router.get("/me/profile", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """Get current user's profile"""
    return serialize_user(current_user)


@router.put("/me/profile", response_model=UserResponse)
async def update_my_profile(
    request: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update current user's profile"""
    service = UserService(db)
    
    update_data = {}
    if request.first_name is not None:
        update_data["first_name"] = request.first_name
    if request.last_name is not None:
        update_data["last_name"] = request.last_name
    if request.email is not None:
        update_data["email"] = request.email
    if request.avatar_url is not None:
        update_data["avatar_url"] = request.avatar_url
    if request.profile is not None:
        update_data["profile"] = request.profile
    if request.preferences is not None:
        update_data["preferences"] = request.preferences
    if request.profile_visibility is not None:
        update_data["profile_visibility"] = request.profile_visibility
    
    user = await service.update_user(str(current_user.id), update_data)
    return serialize_user(user)


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a custom avatar image."""
    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: JPEG, PNG, WebP, GIF"
        )

    # Validate file size
    contents = await file.read()
    max_size = settings.max_avatar_size_mb * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.max_avatar_size_mb}MB"
        )

    # Determine file extension
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
    ext = ext_map.get(file.content_type, "png")

    # Save file
    avatars_dir = os.path.join(settings.upload_dir, "avatars")
    os.makedirs(avatars_dir, exist_ok=True)

    filename = f"{current_user.id}.{ext}"
    file_path = os.path.join(avatars_dir, filename)

    # Remove old avatar files for this user
    for old_file in os.listdir(avatars_dir):
        if old_file.startswith(str(current_user.id)):
            os.remove(os.path.join(avatars_dir, old_file))

    with open(file_path, "wb") as f:
        f.write(contents)

    # Update user: set avatar_url to relative path and disable Gravatar
    avatar_url = f"/api/users/avatar/{filename}"
    prefs = dict(current_user.preferences or {})
    prefs["use_gravatar"] = False

    service = UserService(db)
    user = await service.update_user(str(current_user.id), {
        "avatar_url": avatar_url,
        "preferences": prefs,
    })
    return serialize_user(user)


@router.get("/avatar/{filename}")
async def get_avatar(filename: str):
    """Serve an avatar image file."""
    file_path = os.path.join(settings.upload_dir, "avatars", filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    from fastapi.responses import FileResponse
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    ext = os.path.splitext(filename)[1].lower()
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(file_path, media_type=media_type)


@router.post("/me/change-password")
async def change_my_password(
    request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change current user's password"""
    service = UserService(db)
    await service.change_password(
        str(current_user.id),
        request.current_password,
        request.new_password
    )

    return {"message": "Password changed successfully"}

@router.get("/{user_id}/profile")
async def get_public_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a user's public profile.
    
    Accessible if:
    - The target user has profile_visibility='public'
    - The viewer is the target user themselves
    - The viewer shares a workspace with the target user
    Otherwise returns 404 to avoid leaking private profile existence.
    """
    from sqlalchemy import select, and_, or_
    from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
    
    service = UserService(db)
    target_user = await service.get_by_id(user_id)
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    viewer_id = str(current_user.id)
    target_id = str(target_user.id)
    
    # Always allow self-view
    can_view = viewer_id == target_id
    
    # Allow if profile is public
    if not can_view and target_user.profile_visibility == "public":
        can_view = True
    
    # Allow if they share a workspace
    if not can_view:
        result = await db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.user_id == viewer_id,
                    WorkspaceMember.workspace_id.in_(
                        select(WorkspaceMember.workspace_id).where(
                            WorkspaceMember.user_id == target_id
                        )
                    )
                )
            )
        )
        can_view = result.scalar_one_or_none() is not None
        
        # Also check if one owns a workspace the other is member of
        if not can_view:
            result = await db.execute(
                select(SharedWorkspace).where(
                    or_(
                        and_(
                            SharedWorkspace.owner_id == viewer_id,
                            SharedWorkspace.members.any(WorkspaceMember.user_id == target_id)
                        ),
                        and_(
                            SharedWorkspace.owner_id == target_id,
                            SharedWorkspace.members.any(WorkspaceMember.user_id == viewer_id)
                        )
                    )
                )
            )
            can_view = result.scalar_one_or_none() is not None
    
    if not can_view:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": str(target_user.id),
        "username": target_user.username,
        "display_name": target_user.display_name,
        "avatar_url": target_user.get_avatar_url(),
        "role": target_user.role,
        "profile_visibility": target_user.profile_visibility or "private",
        "profile": target_user.profile or {},
        "created_at": target_user.created_at.isoformat() if target_user.created_at else None,
    }


@router.get("/", response_model=UserListResponse)
async def list_users(
    role: Optional[str] = Query(None, description="Filter by role"),
    status: Optional[str] = Query(None, description="Filter by status: active, disabled"),
    search: Optional[str] = Query(None, description="Search username/email/full_name"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions(Permission.USERS_READ))
):
    """List users with filtering and pagination (Admin/Moderator only)"""
    service = UserService(db)
    result = await service.list_users(
        role=role,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit
    )
    
    return {
        "users": [serialize_user(u) for u in result["users"]],
        "pagination": result["pagination"]
    }


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateRequest,
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions(Permission.USERS_CREATE))
):
    """Create a new user (Admin/Moderator only)"""
    service = UserService(db)
    user = await service.create_user(
        username=request.username,
        email=request.email,
        password=request.password,
        role=request.role,
        first_name=request.first_name,
        last_name=request.last_name,
        avatar_url=request.avatar_url,
        credits=request.credits,
        created_by=current_user
    )
    
    return serialize_user(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user by ID. Users can view own profile, admins can view any."""
    # Check permissions
    checker = PermissionChecker(current_user)
    
    # Users can view their own profile
    if str(current_user.id) != user_id:
        # Otherwise need read permission
        checker.require(Permission.USERS_READ)
    
    service = UserService(db)
    user = await service.get_by_id(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return serialize_user(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update user. Users can update own profile, admins can update any."""
    checker = PermissionChecker(current_user)
    
    # Users can update their own profile (except role and credits)
    if str(current_user.id) != user_id:
        checker.require(Permission.USERS_UPDATE)
    else:
        # Regular users can't update their own role or credits
        if request.role is not None or request.nuke_balance is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update role or credit balance"
            )
    
    service = UserService(db)
    
    # Build update data
    update_data = {}
    if request.first_name is not None:
        update_data["first_name"] = request.first_name
    if request.last_name is not None:
        update_data["last_name"] = request.last_name
    if request.email is not None:
        update_data["email"] = request.email
    if request.avatar_url is not None:
        update_data["avatar_url"] = request.avatar_url
    if request.profile is not None:
        update_data["profile"] = request.profile
    if request.preferences is not None:
        update_data["preferences"] = request.preferences
    if request.role is not None:
        update_data["role"] = request.role
    if request.nuke_balance is not None:
        update_data["nuke_balance"] = request.nuke_balance
    
    user = await service.update_user(user_id, update_data, updated_by=current_user)
    return serialize_user(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions(Permission.USERS_DELETE))
):
    """Delete user (Admin only)"""
    # Prevent self-deletion
    if str(current_user.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    service = UserService(db)
    await service.delete_user(user_id)
    return None


@router.post("/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: str,
    request: DisableUserRequest,
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions(Permission.USERS_UPDATE))
):
    """Disable or enable user (Admin/Moderator only)"""
    # Prevent self-disabling
    if str(current_user.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account"
        )
    
    service = UserService(db)
    user = await service.disable_user(user_id, disabled=request.disabled, reason=request.reason)
    return serialize_user(user)


@router.post("/{user_id}/impersonate")
async def impersonate_user(
    user_id: str,
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions(Permission.USERS_IMPERSONATE))
):
    """Impersonate a user (Super Admin only). Returns temporary JWT."""
    from app.api.auth import create_access_token
    
    service = UserService(db)
    user = await service.get_by_id(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create short-lived token for impersonation
    token = create_access_token(
        data={"sub": user.username, "impersonated_by": str(current_user.id)},
        expires_delta=__import__('datetime').timedelta(minutes=30)
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "impersonated_user": serialize_user(user)
    }


# ========== User Profile Endpoints ==========

@router.get("/{user_id}/servers")
async def get_user_servers(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's servers"""
    from app.models.server import Server
    from sqlalchemy import select
    
    # Check access
    checker = PermissionChecker(current_user)
    if str(current_user.id) != user_id:
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_WRITE_ALL])
    
    result = await db.execute(
        select(Server).where(Server.user_id == user_id)
    )
    servers = result.scalars().all()
    
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status,
                "external_url": s.external_url,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in servers
        ]
    }


@router.get("/{user_id}/resources")
async def get_user_resources(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's resource usage statistics"""
    service = UserService(db)
    stats = await service.get_user_stats(user_id)
    
    return stats


@router.get("/me/activity")
async def get_my_activity(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    action: str = Query(None),
    target_type: str = Query(None),
    from_date: str = Query(None),
    to_date: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get paginated activity feed for the current user"""
    from sqlalchemy import select, func, desc, and_
    from app.models.activity_log import ActivityLog
    from datetime import datetime

    query = select(ActivityLog).where(ActivityLog.actor_id == current_user.id)

    if action:
        query = query.where(ActivityLog.action.ilike(f"%{action}%"))
    if target_type:
        query = query.where(ActivityLog.target_type.ilike(f"%{target_type}%"))
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
            query = query.where(ActivityLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
            query = query.where(ActivityLog.created_at <= dt)
        except ValueError:
            pass

    # Count total
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0

    # Paginate
    offset = (page - 1) * limit
    query = query.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    activities = result.scalars().all()

    return {
        "activities": [
            {
                "id": str(a.id),
                "actor_id": str(a.actor_id) if a.actor_id else None,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": str(a.target_id) if a.target_id else None,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "details": a.details or {}
            }
            for a in activities
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }

