"""OAuth/OIDC authentication service with discovery support."""

import secrets
import base64
import hashlib
from typing import Optional, Dict, Any
import aiohttp
from urllib.parse import urlencode
from app.config import settings


class OAuthService:
    """Handle OAuth 2.0 / OIDC authentication flows."""
    
    def __init__(self):
        self.discovery_data: Optional[Dict[str, Any]] = None
        self._discovery_loaded = False
    
    @property
    def is_configured(self) -> bool:
        """Check if OAuth is properly configured."""
        return bool(
            settings.oauth_client_id and 
            settings.oauth_client_secret and
            (settings.oauth_discovery_url or settings.oauth_authorize_url)
        )
    
    async def _load_discovery(self) -> Dict[str, Any]:
        """Load OIDC discovery document if URL is configured."""
        if self._discovery_loaded:
            return self.discovery_data or {}
        
        self._discovery_loaded = True
        
        if not settings.oauth_discovery_url:
            return {}
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
                async with session.get(settings.oauth_discovery_url) as response:
                    response.raise_for_status()
                    self.discovery_data = await response.json()
                    return self.discovery_data
        except Exception as e:
            print(f"OAuth discovery failed: {e}")
            return {}
    
    def _get_endpoint(self, endpoint_type: str) -> Optional[str]:
        """Get endpoint URL from discovery or manual config."""
        # Try discovery first
        if self.discovery_data:
            discovery_map = {
                "authorize": "authorization_endpoint",
                "token": "token_endpoint",
                "userinfo": "userinfo_endpoint",
                "logout": "end_session_endpoint",
            }
            key = discovery_map.get(endpoint_type)
            if key and key in self.discovery_data:
                return self.discovery_data[key]
        
        # Fall back to manual config
        manual_map = {
            "authorize": settings.oauth_authorize_url,
            "token": settings.oauth_token_url,
            "userinfo": settings.oauth_userdata_url,
            "logout": settings.oauth_logout_url,
        }
        return manual_map.get(endpoint_type)
    
    async def get_authorize_url(self, state: str, code_challenge: Optional[str] = None) -> str:
        """Build OAuth authorization URL."""
        await self._load_discovery()
        
        authorize_url = self._get_endpoint("authorize")
        if not authorize_url:
            raise ValueError("OAuth authorize URL not configured")
        
        params = {
            "client_id": settings.oauth_client_id,
            "response_type": "code",
            "redirect_uri": settings.oauth_callback_url,
            "scope": settings.oauth_scope,
            "state": state,
        }
        
        # Add PKCE if enabled
        if settings.oauth_pkce_enabled and code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        
        query = urlencode(params)
        return f"{authorize_url}?{query}"
    
    async def exchange_code(self, code: str, code_verifier: Optional[str] = None) -> Dict[str, Any]:
        """Exchange authorization code for tokens."""
        await self._load_discovery()
        
        token_url = self._get_endpoint("token")
        if not token_url:
            raise ValueError("OAuth token URL not configured")
        
        data = {
            "grant_type": "authorization_code",
            "client_id": settings.oauth_client_id,
            "client_secret": settings.oauth_client_secret,
            "code": code,
            "redirect_uri": settings.oauth_callback_url,
        }
        
        if settings.oauth_pkce_enabled and code_verifier:
            data["code_verifier"] = code_verifier
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
            async with session.post(token_url, data=data) as response:
                response.raise_for_status()
                return await response.json()
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Fetch user info from OAuth provider."""
        await self._load_discovery()
        
        userinfo_url = self._get_endpoint("userinfo")
        if not userinfo_url:
            # If no userinfo endpoint, decode ID token
            return {}
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
            async with session.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            ) as response:
                response.raise_for_status()
                return await response.json()
    
    def generate_state(self) -> str:
        """Generate a random state parameter."""
        return secrets.token_urlsafe(32)
    
    def generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        return verifier, challenge
    
    def extract_user_data(self, userinfo: Dict[str, Any]) -> Dict[str, Any]:
        """Extract normalized user data from OAuth provider response."""
        username_claim = settings.oauth_username_claim
        email_claim = settings.oauth_email_claim
        name_claim = settings.oauth_name_claim
        picture_claim = settings.oauth_picture_claim
        
        username = userinfo.get(username_claim) or userinfo.get("sub") or userinfo.get("email", "").split("@")[0]
        email = userinfo.get(email_claim) or userinfo.get("email", "")
        
        # Parse name
        full_name = userinfo.get(name_claim, "")
        first_name = userinfo.get("given_name", "")
        last_name = userinfo.get("family_name", "")
        if full_name and not (first_name or last_name):
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
        
        picture = userinfo.get(picture_claim) or userinfo.get("picture")
        
        return {
            "username": username,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "avatar_url": picture,
            "oauth_id": userinfo.get("sub"),
        }


# Singleton instance
oauth_service = OAuthService()
