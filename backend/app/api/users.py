"""
User API endpoints with RBAC enforcement.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import require_permissions, PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import UserService
from app.services.activity_service import ActivityService

router = APIRouter()


# Request/Response Models
class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6)
    role: str = Field(default="user")
    full_name: Optional[str] = Field(default=None, max_length=255)
    credits: int = Field(default=500, ge=0)


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = None
    profile: Optional[dict] = None
    preferences: Optional[dict] = None
    credit_balance: Optional[int] = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    role: str
    credit_balance: int
    is_active: bool
    is_verified: bool
    last_login: Optional[str]
    created_at: Optional[str]


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
        "full_name": user.full_name,
        "role": user.role,
        "credit_balance": user.credit_balance,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# ========== User CRUD Endpoints ==========

@router.get("/", response_model=UserListResponse)
async def list_users(
    role: Optional[str] = Query(None, description="Filter by role"),
    status: Optional[str] = Query(None, description="Filter by status: active, disabled"),
    search: Optional[str] = Query(None, description="Search username/email/full_name"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
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
        full_name=request.full_name,
        credits=request.credits,
        created_by=current_user
    )
    
    # Log activity
    activity_service = ActivityService(db)
    await activity_service.log(
        action="user_created",
        target_type="user",
        target_id=str(user.id),
        actor_id=str(current_user.id),
        details={"username": user.username, "role": user.role}
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
        if request.role is not None or request.credit_balance is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update role or credit balance"
            )
    
    service = UserService(db)
    
    # Build update data
    update_data = {}
    if request.full_name is not None:
        update_data["full_name"] = request.full_name
    if request.email is not None:
        update_data["email"] = request.email
    if request.profile is not None:
        update_data["profile"] = request.profile
    if request.preferences is not None:
        update_data["preferences"] = request.preferences
    if request.role is not None:
        update_data["role"] = request.role
    if request.credit_balance is not None:
        update_data["credit_balance"] = request.credit_balance
    
    user = await service.update_user(user_id, update_data, updated_by=current_user)
    return serialize_user(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
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
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE])
    
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
    checker = PermissionChecker(current_user)
    if str(current_user.id) != user_id:
        checker.require(Permission.RESOURCES_READ_ALL)
    
    service = UserService(db)
    stats = await service.get_user_stats(user_id)
    
    return stats


# ========== Profile Endpoints (Current User) ==========

@router.get("/me/profile", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user)
):
    """Get current user's profile"""
    return serialize_user(current_user)


@router.put("/me/profile", response_model=UserResponse)
async def update_my_profile(
    request: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update current user's profile"""
    service = UserService(db)
    
    update_data = {}
    if request.full_name is not None:
        update_data["full_name"] = request.full_name
    if request.email is not None:
        update_data["email"] = request.email
    if request.profile is not None:
        update_data["profile"] = request.profile
    if request.preferences is not None:
        update_data["preferences"] = request.preferences
    
    user = await service.update_user(str(current_user.id), update_data)
    return serialize_user(user)


@router.post("/me/change-password")
async def change_my_password(
    request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Change current user's password"""
    service = UserService(db)
    await service.change_password(
        str(current_user.id),
        request.current_password,
        request.new_password
    )
    
    return {"message": "Password changed successfully"}
