"""
Webhook notification service with HMAC signing and retries.
"""

import hmac
import hashlib
import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, UTC
import aiohttp


class WebhookService:
    """Webhook dispatch service with HMAC-SHA256 signing and retries"""
    
    def __init__(self, secret: Optional[str] = None):
        self.secret = secret or "nukelab-webhook-secret"
    
    def _sign_payload(self, payload: Dict[str, Any]) -> str:
        """Generate HMAC-SHA256 signature for payload"""
        payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(
            self.secret.encode(),
            payload_json.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    async def dispatch(
        self,
        url: str,
        event: str,
        payload: Dict[str, Any],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Dispatch webhook with retries"""
        
        webhook_payload = {
            "event": event,
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "payload": payload,
        }
        
        signature = self._sign_payload(webhook_payload)
        
        headers = {
            "Content-Type": "application/json",
            "X-Nukelab-Signature": f"sha256={signature}",
            "X-Nukelab-Event": event,
        }
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        url,
                        json=webhook_payload,
                        headers=headers
                    ) as response:
                        if response.status < 400:
                            return {
                                "success": True,
                                "status_code": response.status,
                                "attempt": attempt + 1,
                            }
                        else:
                            last_error = f"HTTP {response.status}"
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                await asyncio.sleep(wait_time)
        
        return {
            "success": False,
            "error": last_error,
            "attempts": max_retries,
        }
    
    async def dispatch_to_user(
        self,
        user_id: str,
        event: str,
        payload: Dict[str, Any],
        db=None
    ) -> Dict[str, Any]:
        """Dispatch webhook to user's configured webhook URL"""
        if not db:
            return {"success": False, "error": "No database session"}
        
        from sqlalchemy import select
        from app.models.user import User
        
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.preferences:
            return {"success": False, "error": "User not found or no preferences"}
        
        webhook_url = user.preferences.get('webhook_url')
        if not webhook_url:
            return {"success": False, "error": "No webhook URL configured"}
        
        return await self.dispatch(webhook_url, event, payload)
