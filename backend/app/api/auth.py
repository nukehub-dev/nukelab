import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from dataclasses import dataclass
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.api_token import ApiToken
from app.models.refresh_token import RefreshToken
from app.core.security import get_user_permissions

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class CustomHTTPBearer(HTTPBearer):
    """Custom HTTP Bearer that accepts both 'Bearer' and 'Token' schemes"""
    async def __call__(self, request: Request):
        authorization = request.headers.get("Authorization")
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        # Support both "Bearer <token>" and "Token <token>"
        scheme = ""
        token = ""
        if " " in authorization:
            scheme, token = authorization.split(" ", 1)
        
        if scheme.lower() not in ["bearer", "token"]:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication scheme",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        return token


security_scheme = CustomHTTPBearer(auto_error=True)


@dataclass
class AuthContext:
    """Authentication context carrying both user and auth method metadata."""
    user: User
    auth_method: str  # "jwt", "api_token"
    token_scopes: List[str]
    api_token_id: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def create_refresh_token_for_user(
    user_id: str,
    db: AsyncSession,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> str:
    """Create a new refresh token, store hashed version in DB, return plaintext."""
    plaintext = secrets.token_urlsafe(32)
    token_hash = pwd_context.hash(plaintext)
    expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_expire_days)

    refresh_token = RefreshToken(
        user_id=uuid.UUID(user_id),
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_token)
    await db.commit()
    return plaintext


async def verify_refresh_token(plaintext: str, db: AsyncSession) -> Optional[RefreshToken]:
    """Verify a refresh token by checking all non-revoked, non-expired tokens for the user."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.revoked_at == None,
            RefreshToken.expires_at > datetime.utcnow(),
        )
    )
    tokens = result.scalars().all()
    for rt in tokens:
        if pwd_context.verify(plaintext, rt.token_hash):
            return rt
    return None


async def revoke_refresh_token(plaintext: str, db: AsyncSession) -> bool:
    """Revoke a refresh token."""
    rt = await verify_refresh_token(plaintext, db)
    if rt:
        rt.revoked_at = datetime.utcnow()
        await db.commit()
        return True
    return False


async def get_auth_context(
    request: Request,
    token: str = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> AuthContext:
    """Authenticate request and return AuthContext with user + auth metadata."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try JWT first
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        if username:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                context = AuthContext(
                    user=user,
                    auth_method="jwt",
                    token_scopes=[],
                )
                request.state.auth_context = context
                return context
    except JWTError:
        pass

    # Try API token with fast prefix lookup
    token_prefix = token[:16] if len(token) >= 16 else token

    # Fast path: query by prefix
    result = await db.execute(
        select(ApiToken).where(
            and_(
                ApiToken.token_prefix == token_prefix,
                ApiToken.is_active == True,
                ApiToken.revoked_at == None,
            )
        )
    )
    api_tokens = result.scalars().all()

    for api_token in api_tokens:
        if verify_password(token, api_token.token_hash):
            if api_token.expires_at and api_token.expires_at < datetime.utcnow():
                raise credentials_exception

            # Update usage
            api_token.last_used_at = datetime.utcnow()
            api_token.usage_count = (api_token.usage_count or 0) + 1
            await db.commit()

            result = await db.execute(select(User).where(User.id == api_token.user_id))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                context = AuthContext(
                    user=user,
                    auth_method="api_token",
                    token_scopes=api_token.scopes or [],
                    api_token_id=str(api_token.id),
                )
                request.state.auth_context = context
                return context
            raise credentials_exception

    raise credentials_exception


async def get_current_user(auth_context: AuthContext = Depends(get_auth_context)) -> User:
    """Return the authenticated user (backward-compatible with existing endpoints)."""
    return auth_context.user


def require_scopes(*required_scopes: str):
    """Dependency factory that enforces API token scope restrictions.

    JWT-authenticated requests bypass scope checks (full user permissions).
    API token requests must have at least one of the required scopes.

    Usage:
        @router.get("/servers")
        async def list_servers(
            current_user: User = Depends(get_current_user),
            _ = Depends(require_scopes("servers:read")),
        ):
            ...
    """
    async def checker(
        request: Request,
        current_user: User = Depends(get_current_user),
    ):
        auth_context = getattr(request.state, "auth_context", None)
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        # JWT auth bypasses scope checks
        if auth_context.auth_method == "jwt":
            return

        # API token auth must match required scopes
        token_scopes = set(auth_context.token_scopes or [])

        for scope in required_scopes:
            if scope in token_scopes:
                continue
            # Support wildcard patterns like "servers:*"
            if ":" in scope:
                prefix = scope.split(":")[0]
                if f"{prefix}:*" in token_scopes:
                    continue
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient scope. Required: {scope}",
            )

    return checker


def require_jwt_auth():
    """Dependency factory that rejects API token authentication.

    Token management and other sensitive operations should only be
    accessible via JWT/session authentication, not scoped API tokens.

    Usage:
        @router.post("/tokens")
        async def create_token(
            current_user: User = Depends(get_current_user),
            _ = Depends(require_jwt_auth()),
        ):
            ...
    """
    async def checker(
        request: Request,
        current_user: User = Depends(get_current_user),
    ):
        auth_context = getattr(request.state, "auth_context", None)
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        if auth_context.auth_method != "jwt":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="JWT authentication required for this operation",
            )

    return checker


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    if settings.auth_mode == "oauth":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password login is disabled. Use OAuth instead."
        )
    
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update login tracking
    user.last_login = datetime.utcnow()
    user.login_count = (user.login_count or 0) + 1
    
    # Update security tracking
    security = dict(user.security or {})
    security["last_login_at"] = datetime.utcnow().isoformat()
    user.security = security
    
    await db.commit()
    
    access_token = create_access_token(data={"sub": user.username})
    refresh_token = await create_refresh_token_for_user(
        str(user.id), db,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_remote_address(request),
    )

    response = JSONResponse(content={
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    })
    response.set_cookie(
        key="nukelab_token",
        value=access_token,
        max_age=settings.session_max_age,
        httponly=settings.session_httponly,
        secure=settings.session_secure,
        samesite=settings.session_samesite,
    )
    return response


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
async def refresh_token_endpoint(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access token + new refresh token (rotation)."""
    rt = await verify_refresh_token(request.refresh_token, db)
    if not rt:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    # Revoke the old token
    rt.revoked_at = datetime.utcnow()
    rt.last_used_at = datetime.utcnow()

    # Get user
    result = await db.execute(select(User).where(User.id == rt.user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Create new tokens
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = await create_refresh_token_for_user(
        str(user.id), db,
        user_agent=rt.user_agent,
        ip_address=rt.ip_address,
    )
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout_endpoint(request: Request, body: Optional[RefreshRequest] = None, db: AsyncSession = Depends(get_db)):
    """Revoke refresh token and clear cookies."""
    if body and body.refresh_token:
        await revoke_refresh_token(body.refresh_token, db)

    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie("nukelab_token")
    return response


@router.get("/verify")
async def verify_auth(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify authentication for nginx auth_request module.
    
    Returns 200 with X-User-Id header if valid, 401 otherwise.
    """
    authorization = request.headers.get("Authorization", "")
    token = ""
    
    if " " in authorization:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() not in ["bearer", "token"]:
            raise HTTPException(status_code=401, detail="Invalid scheme")
    elif authorization:
        token = authorization
    else:
        # Try cookie
        cookie_token = request.cookies.get("nukelab_token")
        if cookie_token:
            token = cookie_token
        else:
            raise HTTPException(status_code=401, detail="Missing token")
    
    # Try JWT
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        if username:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                from fastapi.responses import Response
                return Response(
                    status_code=200,
                    headers={"X-User-Id": str(user.id)}
                )
    except JWTError:
        pass
    
    # Try API token
    result = await db.execute(
        select(ApiToken).where(
            ApiToken.is_active == True,
            ApiToken.revoked_at == None
        )
    )
    api_tokens = result.scalars().all()
    
    for api_token in api_tokens:
        if verify_password(token, api_token.token_hash):
            if api_token.expires_at and api_token.expires_at < datetime.utcnow():
                raise HTTPException(status_code=401, detail="Token expired")
            
            result = await db.execute(select(User).where(User.id == api_token.user_id))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                from fastapi.responses import Response
                return Response(
                    status_code=200,
                    headers={"X-User-Id": str(user.id)}
                )
    
    raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("user:read")),
):
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.display_name,
        "role": current_user.role,
        "permissions": get_user_permissions(current_user),
        "nuke_balance": current_user.nuke_balance,
        "profile": current_user.profile or {},
        "preferences": current_user.preferences or {},
        "oauth_provider": current_user.oauth_provider,
        "is_active": current_user.is_active,
        "is_verified": current_user.is_verified,
        "login_count": current_user.login_count,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/methods")
async def get_auth_methods():
    """Get available authentication methods."""
    from app.services.oauth_service import oauth_service
    
    methods = []
    
    # Local/password auth
    if settings.auth_mode in ("local", "both"):
        methods.append({
            "type": "local",
            "name": "Username & Password",
            "enabled": True
        })
    
    # OAuth
    if oauth_service.is_configured and settings.auth_mode in ("oauth", "both"):
        methods.append({
            "type": "oauth",
            "name": settings.oauth_provider_name or "OAuth Provider",
            "enabled": True
        })
    
    return {
        "methods": methods,
        "auth_mode": settings.auth_mode,
        "oauth_enabled": oauth_service.is_configured and settings.auth_mode in ("oauth", "both"),
        "oauth_provider_name": settings.oauth_provider_name or None,
        "oauth_profile_url": settings.oauth_profile_url or None,
    }


@router.get("/oauth/login")
async def oauth_login(sync: Optional[str] = None):
    """Redirect to OAuth provider authorization endpoint."""
    from app.services.oauth_service import oauth_service
    
    if not oauth_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth not configured"
        )
    
    if settings.auth_mode == "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth login is disabled"
        )
    
    is_sync = sync == "1"
    state = oauth_service.generate_state()
    code_verifier = None
    code_challenge = None
    
    if settings.oauth_pkce_enabled:
        code_verifier, code_challenge = oauth_service.generate_pkce()
    
    # Store state in cookie for verification on callback
    from fastapi.responses import RedirectResponse
    authorize_url = await oauth_service.get_authorize_url(state, code_challenge)
    
    # For sync, add prompt=none so Keycloak doesn't show login page if session exists
    if is_sync:
        authorize_url += "&prompt=none"
    
    response = RedirectResponse(url=authorize_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.session_secure,
        samesite=settings.session_samesite
    )
    
    if code_verifier:
        response.set_cookie(
            key="oauth_verifier",
            value=code_verifier,
            max_age=600,
            httponly=True,
            secure=settings.session_secure,
            samesite=settings.session_samesite
        )
    
    if is_sync:
        response.set_cookie(
            key="oauth_sync",
            value="1",
            max_age=600,
            httponly=True,
            secure=settings.session_secure,
            samesite=settings.session_samesite
        )
    
    return response


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle OAuth callback from identity provider."""
    from app.services.oauth_service import oauth_service
    from fastapi.responses import RedirectResponse
    
    # Handle OAuth errors
    # Use FRONTEND_URL if explicitly set (dev Vite server), otherwise use PUBLIC_URL (production Traefik)
    frontend_base = (settings.frontend_url or settings.public_url).rstrip('/')
    
    # Check if this is a sync request for error handling
    is_sync = request.cookies.get("oauth_sync") == "1"
    
    if error:
        error_msg = error_description or error
        if is_sync:
            redirect_url = f"{frontend_base}/settings/profile?sync=error&msg={error_msg}"
            response = RedirectResponse(url=redirect_url)
            response.delete_cookie("oauth_state")
            response.delete_cookie("oauth_verifier")
            response.delete_cookie("oauth_sync")
            return response
        redirect_url = f"{frontend_base}/login?error={error_msg}"
        return RedirectResponse(url=redirect_url)
    
    if not code:
        if is_sync:
            redirect_url = f"{frontend_base}/settings/profile?sync=error&msg=Missing+authorization+code"
            response = RedirectResponse(url=redirect_url)
            response.delete_cookie("oauth_state")
            response.delete_cookie("oauth_verifier")
            response.delete_cookie("oauth_sync")
            return response
        return RedirectResponse(url=f"{frontend_base}/login?error=Missing authorization code")
    
    # Verify state to prevent CSRF
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        if is_sync:
            redirect_url = f"{frontend_base}/settings/profile?sync=error&msg=Invalid+state+parameter"
            response = RedirectResponse(url=redirect_url)
            response.delete_cookie("oauth_state")
            response.delete_cookie("oauth_verifier")
            response.delete_cookie("oauth_sync")
            return response
        return RedirectResponse(url=f"{frontend_base}/login?error=Invalid state parameter")
    
    # Get PKCE verifier
    code_verifier = request.cookies.get("oauth_verifier") if settings.oauth_pkce_enabled else None
    
    try:
        # Exchange code for tokens
        token_data = await oauth_service.exchange_code(code, code_verifier)
        access_token = token_data.get("access_token")
        
        if not access_token:
            return RedirectResponse(url=f"{frontend_base}/login?error=Failed to obtain access token")
        
        # Get user info
        userinfo = await oauth_service.get_user_info(access_token)
        
        # Also try to get claims from ID token if userinfo is empty
        id_token = token_data.get("id_token")
        if not userinfo and id_token:
            # Decode ID token (without verification - provider already verified)
            try:
                id_payload = jwt.decode(id_token, options={"verify_signature": False})
                userinfo = id_payload
            except Exception:
                pass
        
        if not userinfo:
            return RedirectResponse(url=f"{frontend_base}/login?error=Failed to get user information")
        
        # Extract normalized user data
        user_data = oauth_service.extract_user_data(userinfo)
        
        # Find or create user
        result = await db.execute(
            select(User).where(User.oauth_id == user_data["oauth_id"])
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Try finding by email
            result = await db.execute(
                select(User).where(User.email == user_data["email"])
            )
            user = result.scalar_one_or_none()
        
        if user:
            # Update existing user with OAuth info
            user.oauth_provider = "oauth"
            user.oauth_id = user_data["oauth_id"]
            if user_data.get("first_name"):
                user.first_name = user_data["first_name"]
            if user_data.get("last_name"):
                user.last_name = user_data["last_name"]
            if user_data.get("email"):
                user.email = user_data["email"]
            # Merge extra OAuth profile fields (organization, department, about, etc.)
            if user_data.get("extra_profile"):
                profile = dict(user.profile or {})
                profile.update(user_data["extra_profile"])
                user.profile = profile
        else:
            # Create new user
            user = User(
                username=user_data["username"],
                email=user_data["email"],
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                oauth_provider="oauth",
                oauth_id=user_data["oauth_id"],
                role="user",
                is_active=True,
                is_verified=True,
                profile=user_data.get("extra_profile") or {},
            )
            db.add(user)
        
        # Check if this is a sync request
        is_sync = request.cookies.get("oauth_sync") == "1"
        
        if is_sync:
            # Sync mode: update profile without creating new session
            await db.commit()
            await db.refresh(user)
            redirect_url = f"{frontend_base}/settings/profile?sync=success"
            response = RedirectResponse(url=redirect_url)
            response.delete_cookie("oauth_state")
            response.delete_cookie("oauth_verifier")
            response.delete_cookie("oauth_sync")
            return response
        
        # Normal login flow
        security = dict(user.security or {})
        
        # Store OAuth refresh token for future sync
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            from app.core.token_encryption import encrypt_token
            security["oauth_refresh_token"] = encrypt_token(refresh_token)
        
        # Update login tracking
        user.last_login = datetime.utcnow()
        user.login_count = (user.login_count or 0) + 1
        security["last_login_at"] = datetime.utcnow().isoformat()
        security["oauth_login"] = True
        user.security = security
        
        await db.commit()
        await db.refresh(user)
        
        # Create JWT token
        access_token_jwt = create_access_token(data={"sub": user.username})
        refresh_token_plain = await create_refresh_token_for_user(
            str(user.id), db,
            user_agent=request.headers.get("user-agent"),
            ip_address=get_remote_address(request),
        )

        # Redirect to frontend with tokens
        redirect_url = f"{frontend_base}/login?token={access_token_jwt}&refresh={refresh_token_plain}"
        response = RedirectResponse(url=redirect_url)

        # Set cookies
        response.set_cookie(
            key="nukelab_token",
            value=access_token_jwt,
            max_age=settings.session_max_age,
            httponly=settings.session_httponly,
            secure=settings.session_secure,
            samesite=settings.session_samesite
        )

        # Clear OAuth cookies
        response.delete_cookie("oauth_state")
        response.delete_cookie("oauth_verifier")

        return response
        
    except Exception as e:
        import traceback
        print(f"OAuth callback error: {traceback.format_exc()}")
        
        # Check if sync mode for error handling too
        is_sync = request.cookies.get("oauth_sync") == "1"
        if is_sync:
            error_msg = str(e)
            redirect_url = f"{frontend_base}/settings/profile?sync=error&msg={error_msg}"
            response = RedirectResponse(url=redirect_url)
            response.delete_cookie("oauth_state")
            response.delete_cookie("oauth_verifier")
            response.delete_cookie("oauth_sync")
            return response
        
        return RedirectResponse(url=f"{frontend_base}/login?error=OAuth authentication failed: {str(e)}")



@router.post("/oauth/sync")
async def oauth_sync(
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    _scopes = Depends(require_scopes("user:update")),
    db: AsyncSession = Depends(get_db)
):
    """Sync user profile from OAuth provider using stored refresh token."""
    from app.services.oauth_service import oauth_service
    from app.core.token_encryption import decrypt_token
    import aiohttp
    
    if not current_user.oauth_provider or not current_user.security:
        raise HTTPException(status_code=400, detail="Not an OAuth user")
    
    encrypted_refresh = current_user.security.get("oauth_refresh_token")
    if not encrypted_refresh:
        raise HTTPException(status_code=400, detail="No refresh token available. Please log out and log back in.")
    
    refresh_token = decrypt_token(encrypted_refresh)
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Invalid refresh token. Please log out and log back in.")
    
    try:
        # Load discovery for token endpoint
        await oauth_service._load_discovery()
        token_url = oauth_service._get_endpoint("token")
        if not token_url:
            raise HTTPException(status_code=500, detail="OAuth token URL not configured")
        
        # Exchange refresh token for access token
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
            async with session.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.oauth_client_id,
                    "client_secret": settings.oauth_client_secret,
                    "refresh_token": refresh_token,
                }
            ) as resp:
                resp.raise_for_status()
                token_data = await resp.json()
        
        access_token = token_data.get("access_token")
        new_refresh_token = token_data.get("refresh_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to refresh access token")
        
        # Update stored refresh token if a new one was issued
        if new_refresh_token:
            from app.core.token_encryption import encrypt_token
            security = dict(current_user.security or {})
            security["oauth_refresh_token"] = encrypt_token(new_refresh_token)
            current_user.security = security
        
        # Fetch fresh userinfo
        userinfo = await oauth_service.get_user_info(access_token)
        if not userinfo:
            id_token = token_data.get("id_token")
            if id_token:
                try:
                    id_payload = jwt.decode(id_token, options={"verify_signature": False})
                    userinfo = id_payload
                except Exception:
                    pass
        
        if not userinfo:
            raise HTTPException(status_code=400, detail="Failed to get user information")
        
        # Extract and update user data
        user_data = oauth_service.extract_user_data(userinfo)
        
        if user_data.get("first_name"):
            current_user.first_name = user_data["first_name"]
        if user_data.get("last_name"):
            current_user.last_name = user_data["last_name"]
        if user_data.get("email"):
            current_user.email = user_data["email"]
        if user_data.get("extra_profile"):
            profile = dict(current_user.profile or {})
            profile.update(user_data["extra_profile"])
            current_user.profile = profile
        
        await db.commit()
        await db.refresh(current_user)
        
        from app.api.users import serialize_user
        return serialize_user(current_user)
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("User sync failed")
        raise HTTPException(status_code=500, detail="Sync failed. Please try again or contact support.")
