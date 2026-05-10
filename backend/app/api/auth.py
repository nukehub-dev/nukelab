from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.api_token import ApiToken
from app.core.security import get_user_permissions

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


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(token: str = Depends(security_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Get the original authorization header to determine scheme
    # We need to check if this was a "Token" or "Bearer" request
    # Since security_scheme strips the scheme, we need to look at the raw header
    # But we don't have access to the request here... 
    # Alternative: try JWT first, if that fails, try API token
    
    # Try JWT first
    user = None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        if username:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
    except JWTError:
        pass
    
    if user:
        return user
    
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
            # Check expiration
            if api_token.expires_at and api_token.expires_at < datetime.utcnow():
                raise credentials_exception
            
            # Update usage
            api_token.last_used_at = datetime.utcnow()
            api_token.usage_count += 1
            await db.commit()
            
            # Return the associated user
            result = await db.execute(select(User).where(User.id == api_token.user_id))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                return user
            raise credentials_exception
    
    raise credentials_exception


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
    user.login_count += 1
    
    # Update security tracking
    security = user.security or {}
    security["last_login_at"] = datetime.utcnow().isoformat()
    user.security = security
    
    await db.commit()
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


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
async def get_me(current_user: User = Depends(get_current_user)):
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
        "oauth_enabled": oauth_service.is_configured and settings.auth_mode in ("oauth", "both")
    }


@router.get("/oauth/login")
async def oauth_login():
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
    
    state = oauth_service.generate_state()
    code_verifier = None
    code_challenge = None
    
    if settings.oauth_pkce_enabled:
        code_verifier, code_challenge = oauth_service.generate_pkce()
    
    # Store state in cookie for verification on callback
    from fastapi.responses import RedirectResponse
    authorize_url = await oauth_service.get_authorize_url(state, code_challenge)
    
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
    
    if error:
        error_msg = error_description or error
        redirect_url = f"{frontend_base}/login?error={error_msg}"
        return RedirectResponse(url=redirect_url)
    
    if not code:
        return RedirectResponse(url=f"{frontend_base}/login?error=Missing authorization code")
    
    # Verify state to prevent CSRF
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
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
            if user_data.get("avatar_url"):
                user.avatar_url = user_data["avatar_url"]
        else:
            # Create new user
            user = User(
                username=user_data["username"],
                email=user_data["email"],
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                avatar_url=user_data.get("avatar_url"),
                oauth_provider="oauth",
                oauth_id=user_data["oauth_id"],
                role="user",
                is_active=True,
                is_verified=True
            )
            db.add(user)
        
        # Update login tracking
        user.last_login = datetime.utcnow()
        user.login_count += 1
        
        security = user.security or {}
        security["last_login_at"] = datetime.utcnow().isoformat()
        security["oauth_login"] = True
        user.security = security
        
        await db.commit()
        await db.refresh(user)
        
        # Create JWT token
        access_token_jwt = create_access_token(data={"sub": user.username})
        
        # Redirect to frontend with token
        redirect_url = f"{frontend_base}/login?token={access_token_jwt}"
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
        return RedirectResponse(url=f"{frontend_base}/login?error=OAuth authentication failed: {str(e)}")
