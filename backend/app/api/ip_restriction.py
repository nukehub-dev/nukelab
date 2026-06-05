"""Admin API for managing IP allowlist/blocklist."""

import uuid
from typing import List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.api.auth import get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.ip_restriction import IPRestriction
from app.middleware.ip_restriction import _invalidate_cache, _get_client_ip

router = APIRouter()


class IPRestrictionCreate(BaseModel):
    ip_range: str = Field(..., min_length=1, max_length=50, description="IP or CIDR range, e.g. 192.168.1.0/24")
    restriction_type: str = Field(..., pattern="^(allow|block)$")
    note: Optional[str] = Field(None, max_length=500)


class IPRestrictionResponse(BaseModel):
    id: str
    ip_range: str
    restriction_type: str
    note: Optional[str]
    is_active: bool
    created_by_id: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.get("/ip-restrictions", response_model=List[IPRestrictionResponse])
async def list_ip_restrictions(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all IP restrictions (allowlist + blocklist)."""
    result = await db.execute(
        select(IPRestriction).order_by(desc(IPRestriction.created_at))
    )
    entries = result.scalars().all()
    return [entry.to_dict() for entry in entries]


@router.post("/ip-restrictions", response_model=IPRestrictionResponse, status_code=status.HTTP_201_CREATED)
async def create_ip_restriction(
    req: IPRestrictionCreate,
    request: Request,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Add a new IP restriction (allow or block)."""
    # Validate IP/CIDR syntax
    try:
        import ipaddress
        ipaddress.ip_network(req.ip_range, strict=False)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid IP range: {req.ip_range}",
        )

    # Prevent admins from blocking their own IP
    if req.restriction_type == "block":
        client_ip = _get_client_ip(request)
        try:
            network = ipaddress.ip_network(req.ip_range, strict=False)
            if ipaddress.ip_address(client_ip) in network:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="You cannot block your own IP address. If you want to restrict access, use an allowlist instead.",
                )
        except ValueError:
            pass  # Invalid IP comparison, let it through (syntax check already passed)

    entry = IPRestriction(
        id=uuid.uuid4(),
        ip_range=req.ip_range,
        restriction_type=req.restriction_type,
        note=req.note,
        is_active=True,
        created_by_id=current_user.id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    _invalidate_cache()
    return entry.to_dict()


@router.get("/ip-restrictions/my-ip")
async def get_my_ip(request: Request):
    """Return the client's current IP address.

    Useful for admins who want to add their own IP to the allowlist.
    This endpoint is exempt from IP restrictions.
    """
    return {
        "ip": _get_client_ip(request),
        "note": "This is your current IP as seen by the server.",
    }


@router.delete("/ip-restrictions/{restriction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ip_restriction(
    restriction_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Remove an IP restriction by ID."""
    try:
        rid = uuid.UUID(restriction_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid restriction ID",
        )

    result = await db.execute(select(IPRestriction).where(IPRestriction.id == rid))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP restriction not found",
        )

    await db.delete(entry)
    await db.commit()
    _invalidate_cache()
