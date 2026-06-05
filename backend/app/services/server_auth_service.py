"""Production-ready server authentication service.

Uses asymmetric cryptography (RS256) to issue short-lived, server-scoped
access tokens. Containers validate tokens locally using the public key,
eliminating the need for auth_request round-trips to the backend.

Architecture:
- Backend holds the private key, signs tokens
- Containers/sidecars hold the public key, validate tokens
- Tokens are scoped to a specific server and user
- Database tracks issuance for audit and revocation
- Key rotation supported without container redeployment
"""

import uuid
import os
import logging
from datetime import datetime, timedelta, UTC
from typing import Optional, Dict, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.config import settings
from app.models.server_access_token import ServerAccessToken

logger = logging.getLogger(__name__)


class ServerAuthService:
    """Service for managing server access authentication."""
    
    _instance = None
    _private_key = None
    _public_key = None
    _key_id = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def is_enabled(self) -> bool:
        return settings.server_auth_enabled
    
    @property
    def algorithm(self) -> str:
        return settings.server_auth_key_algorithm
    
    def _ensure_keys_exist(self) -> None:
        """Generate RSA key pair if it doesn't exist."""
        private_path = settings.server_auth_private_key_path
        public_path = settings.server_auth_public_key_path
        
        # Create secrets directory if needed
        os.makedirs(os.path.dirname(private_path), mode=0o700, exist_ok=True)
        
        if not os.path.exists(private_path) or not os.path.exists(public_path):
            logger.info("Generating new RSA key pair for server authentication")
            self._generate_key_pair(private_path, public_path)
    
    def _generate_key_pair(self, private_path: str, public_path: str) -> None:
        """Generate a new RSA key pair."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        # Save private key
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(private_path, 'wb') as f:
            f.write(private_pem)
        os.chmod(private_path, 0o600)
        
        # Save public key
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(public_path, 'wb') as f:
            f.write(public_pem)
        os.chmod(public_path, 0o644)
        
        logger.info(f"RSA key pair generated: {private_path}, {public_path}")
    
    def _load_private_key(self) -> str:
        """Load or generate private key."""
        if self._private_key is None:
            self._ensure_keys_exist()
            with open(settings.server_auth_private_key_path, 'rb') as f:
                key_data = f.read()
                # Return as string for python-jose
                self._private_key = key_data.decode('utf-8')
        return self._private_key
    
    def _load_public_key(self) -> str:
        """Load public key."""
        if self._public_key is None:
            self._ensure_keys_exist()
            with open(settings.server_auth_public_key_path, 'rb') as f:
                key_data = f.read()
                self._public_key = key_data.decode('utf-8')
        return self._public_key
    
    def get_key_id(self) -> str:
        """Get current key ID (based on public key hash)."""
        if self._key_id is None:
            public_key = self._load_public_key()
            import hashlib
            self._key_id = hashlib.sha256(public_key.encode()).hexdigest()[:16]
        return self._key_id
    
    def get_public_key_pem(self) -> str:
        """Get public key in PEM format for distribution to containers."""
        return self._load_public_key()
    
    async def generate_access_token(
        self,
        db: AsyncSession,
        server_id: uuid.UUID,
        user_id: uuid.UUID,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        token_type: str = "session",
        custom_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate a short-lived access token for server access.
        
        Args:
            db: Database session
            server_id: Target server ID
            user_id: User requesting access
            client_ip: Client IP for audit
            user_agent: User agent for audit
            token_type: Token type (session, resume, share)
            custom_claims: Additional claims to include
            
        Returns:
            JWT access token string
            
        Raises:
            ValueError: If server auth is disabled
            RateLimitError: If user exceeds token generation rate
        """
        if not self.is_enabled:
            raise ValueError("Server authentication is disabled")
        
        # Check rate limit
        await self._check_rate_limit(db, user_id, server_id)
        
        # Generate unique token ID
        jti = str(uuid.uuid4())
        key_id = self.get_key_id()
        now = datetime.now(UTC).replace(tzinfo=None)
        expires = now + timedelta(seconds=settings.server_auth_token_ttl)
        
        # Build claims
        claims = {
            "iss": settings.app_name,
            "sub": str(user_id),
            "aud": str(server_id),
            "jti": jti,
            "kid": key_id,
            "iat": now,
            "exp": expires,
            "type": token_type,
            "ver": "1",
        }

        if client_ip:
            claims["client_ip"] = client_ip

        if custom_claims:
            claims.update(custom_claims)
        
        # Sign token
        private_key = self._load_private_key()
        token = jwt.encode(claims, private_key, algorithm=self.algorithm)
        
        # Record in database for audit/revocation
        access_token = ServerAccessToken(
            id=uuid.uuid4(),
            server_id=server_id,
            user_id=user_id,
            jti=jti,
            key_id=key_id,
            issued_at=now,
            expires_at=expires,
            client_ip=client_ip,
            user_agent=user_agent,
            token_type=token_type,
        )
        db.add(access_token)
        await db.commit()
        
        logger.info(
            f"Generated server access token: server={server_id}, user={user_id}, "
            f"jti={jti}, type={token_type}, expires={expires.isoformat()}"
        )
        
        return token
    
    async def validate_token(
        self,
        token: str,
        expected_server_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Validate a server access token locally.
        
        This is designed to be used by containers/sidecars.
        
        Args:
            token: JWT token string
            expected_server_id: Optional server ID to validate against
            
        Returns:
            Token claims dict
            
        Raises:
            JWTError: If token is invalid
        """
        if not self.is_enabled:
            raise JWTError("Server authentication is disabled")
        
        public_key = self._load_public_key()
        
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[self.algorithm],
            options={
                "require": ["exp", "iat", "sub", "aud", "jti"],
                "verify_exp": True,
                "verify_iat": True,
            }
        )
        
        # Validate server scope
        if expected_server_id and claims.get("aud") != str(expected_server_id):
            raise JWTError("Token not valid for this server")
        
        return claims
    
    async def revoke_token(
        self,
        db: AsyncSession,
        jti: str,
        reason: str = "user_logout",
    ) -> bool:
        """Revoke an access token before expiry.
        
        Args:
            db: Database session
            jti: Token JWT ID
            reason: Revocation reason
            
        Returns:
            True if token was found and revoked
        """
        result = await db.execute(
            select(ServerAccessToken).where(
                and_(
                    ServerAccessToken.jti == jti,
                    ServerAccessToken.revoked_at.is_(None)
                )
            )
        )
        token = result.scalar_one_or_none()
        
        if token:
            token.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            token.revoked_reason = reason
            await db.commit()
            logger.info(f"Revoked server access token: jti={jti}, reason={reason}")
            return True
        
        return False
    
    async def revoke_server_tokens(
        self,
        db: AsyncSession,
        server_id: uuid.UUID,
        reason: str = "server_stopped",
    ) -> int:
        """Revoke all active tokens for a server.
        
        Called when a server is stopped or deleted.
        
        Returns:
            Number of tokens revoked
        """
        result = await db.execute(
            select(ServerAccessToken).where(
                and_(
                    ServerAccessToken.server_id == server_id,
                    ServerAccessToken.revoked_at.is_(None),
                    ServerAccessToken.expires_at > datetime.now(UTC).replace(tzinfo=None)
                )
            )
        )
        tokens = result.scalars().all()
        
        count = 0
        for token in tokens:
            token.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            token.revoked_reason = reason
            count += 1
        
        if count > 0:
            await db.commit()
            logger.info(f"Revoked {count} tokens for server {server_id}: {reason}")
        
        return count
    
    async def is_token_revoked(self, db: AsyncSession, jti: str) -> bool:
        """Check if a token has been revoked.
        
        Containers call this periodically or when validating tokens.
        """
        result = await db.execute(
            select(ServerAccessToken).where(
                and_(
                    ServerAccessToken.jti == jti,
                    ServerAccessToken.revoked_at.isnot(None)
                )
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def _check_rate_limit(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        server_id: uuid.UUID,
    ) -> None:
        """Check if user has exceeded token generation rate limit."""
        window_start = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        
        result = await db.execute(
            select(func.count(ServerAccessToken.id)).where(
                and_(
                    ServerAccessToken.user_id == user_id,
                    ServerAccessToken.server_id == server_id,
                    ServerAccessToken.issued_at >= window_start
                )
            )
        )
        count = result.scalar()
        
        if count >= settings.server_auth_max_tokens_per_minute:
            logger.warning(
                f"Rate limit exceeded for server access tokens: "
                f"user={user_id}, server={server_id}, count={count}"
            )
            raise ValueError(
                f"Rate limit exceeded: maximum {settings.server_auth_max_tokens_per_minute} "
                "tokens per minute per server"
            )
    
    async def cleanup_expired_tokens(self, db: AsyncSession, max_age_days: int = 7) -> int:
        """Clean up expired tokens older than max_age_days.
        
        Returns:
            Number of tokens deleted
        """
        from sqlalchemy import delete
        
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max_age_days)
        
        result = await db.execute(
            delete(ServerAccessToken).where(
                ServerAccessToken.expires_at < cutoff
            )
        )
        await db.commit()
        
        count = result.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired server access tokens")
        
        return count
    
    async def get_server_access_stats(
        self,
        db: AsyncSession,
        server_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Get access statistics for a server."""
        # Active tokens
        result = await db.execute(
            select(func.count(ServerAccessToken.id)).where(
                and_(
                    ServerAccessToken.server_id == server_id,
                    ServerAccessToken.revoked_at.is_(None),
                    ServerAccessToken.expires_at > datetime.now(UTC).replace(tzinfo=None)
                )
            )
        )
        active_count = result.scalar()
        
        # Total tokens issued (last 24h)
        day_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
        result = await db.execute(
            select(func.count(ServerAccessToken.id)).where(
                and_(
                    ServerAccessToken.server_id == server_id,
                    ServerAccessToken.issued_at >= day_ago
                )
            )
        )
        total_24h = result.scalar()
        
        # Unique users (last 24h)
        result = await db.execute(
            select(func.count(func.distinct(ServerAccessToken.user_id))).where(
                and_(
                    ServerAccessToken.server_id == server_id,
                    ServerAccessToken.issued_at >= day_ago
                )
            )
        )
        unique_users = result.scalar()
        
        return {
            "active_tokens": active_count,
            "tokens_issued_24h": total_24h,
            "unique_users_24h": unique_users,
        }


# Singleton instance
server_auth_service = ServerAuthService()
