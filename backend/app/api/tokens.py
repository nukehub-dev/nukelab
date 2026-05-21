import secrets
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.api.auth import get_current_user, get_password_hash, verify_password, limiter, require_scopes, require_jwt_auth
from app.db.session import get_db
from app.models.user import User
from app.models.api_token import ApiToken

router = APIRouter()

# Valid token scopes for API token access control
VALID_TOKEN_SCOPES = {
    "analytics:read",
    "credits:read",
    "dashboard:read",
    "environments:read",
    "metrics:read",
    "notifications:read", "notifications:write",
    "plans:read",
    "preferences:read", "preferences:write",
    "quotas:read",
    "schedules:read", "schedules:write",
    "servers:read", "servers:start", "servers:stop", "servers:delete", "servers:manage",
    "user:read", "user:update",
    "volumes:read", "volumes:manage",
    "workspaces:read", "workspaces:manage",
}


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Token name (e.g., 'VS Code', 'GitHub Actions')")
    scopes: List[str] = Field(default=["servers:read", "servers:start"], description="Permission scopes")
    expires_days: Optional[int] = Field(default=30, ge=1, le=365, description="Token expiration in days")

    @field_validator('scopes', mode='before')
    @classmethod
    def validate_scope(cls, v):
        if not isinstance(v, list):
            raise ValueError("scopes must be a list")
        for scope in v:
            if scope not in VALID_TOKEN_SCOPES:
                raise ValueError(f"Invalid scope: {scope}. Valid scopes: {', '.join(sorted(VALID_TOKEN_SCOPES))}")
        return v


class TokenResponse(BaseModel):
    id: str
    name: str
    scopes: List[str]
    usage_count: int
    last_used_at: Optional[str]
    created_at: str
    expires_at: Optional[str]
    is_active: bool


class TokenCreateResponse(TokenResponse):
    token: str  # Only returned once on creation


@router.get("", response_model=List[TokenResponse])
async def list_tokens(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """List all API tokens for the current user"""
    result = await db.execute(
        select(ApiToken).where(ApiToken.user_id == current_user.id)
    )
    tokens = result.scalars().all()
    return [token.to_dict() for token in tokens]


@router.post("", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_token(
    request: Request,
    token_data: TokenCreate,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Create a new API token. The token value is only returned once!"""
    # Generate a secure random token
    raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
    token_hash = get_password_hash(raw_token)
    token_prefix = raw_token[:16]

    # Calculate expiration
    expires_at = None
    if token_data.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=token_data.expires_days)

    # Create token record
    api_token = ApiToken(
        user_id=current_user.id,
        name=token_data.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=token_data.scopes,
        expires_at=expires_at,
    )

    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    # Notify user
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.api_key_created(
        user_id=current_user.id,
        key_name=token_data.name
    )

    # Return token with the raw token (only time it's shown)
    response = api_token.to_dict()
    response["token"] = raw_token
    return response


@router.get("/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific token by ID"""
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == current_user.id
            )
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found"
        )

    return token.to_dict()


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def revoke_token(
    request: Request,
    token_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Revoke (soft-delete) an API token"""
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == current_user.id
            )
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found"
        )

    token.is_active = False
    token.revoked_at = datetime.utcnow()
    await db.commit()

    return None


@router.delete("/{token_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def permanently_delete_token(
    request: Request,
    token_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete an API token from the database"""
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == current_user.id
            )
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found"
        )

    await db.delete(token)
    await db.commit()

    return None


@router.post("/{token_id}/regenerate", response_model=TokenCreateResponse)
@limiter.limit("5/minute")
async def regenerate_token(
    request: Request,
    token_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Regenerate an API token (revokes old one, creates new with same settings)"""
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == current_user.id
            )
        )
    )
    old_token = result.scalar_one_or_none()

    if not old_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found"
        )

    # Revoke old token
    old_token.is_active = False
    old_token.revoked_at = datetime.utcnow()

    # Create new token with same settings but fresh expiration
    raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
    token_hash = get_password_hash(raw_token)
    token_prefix = raw_token[:16]

    new_token = ApiToken(
        user_id=current_user.id,
        name=old_token.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=old_token.scopes,
        expires_at=datetime.utcnow() + timedelta(days=30) if old_token.expires_at else None,
    )

    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)

    response = new_token.to_dict()
    response["token"] = raw_token
    return response


@router.get("/{token_id}/usage", response_model=dict)
async def get_token_usage(
    token_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Get usage statistics for a token"""
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == current_user.id
            )
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found"
        )

    return {
        "token_id": str(token.id),
        "name": token.name,
        "usage_count": token.usage_count,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "is_active": token.is_active,
    }
