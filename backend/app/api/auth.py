from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.api_token import ApiToken

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
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
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
        "full_name": current_user.full_name,
        "role": current_user.role,
        "credit_balance": current_user.credit_balance,
        "profile": current_user.profile or {},
        "preferences": current_user.preferences or {},
        "is_active": current_user.is_active,
        "is_verified": current_user.is_verified,
        "login_count": current_user.login_count,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }
