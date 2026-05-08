"""
Email notification service with SMTP and templates.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from app.config import settings


class EmailService:
    """Email service with Jinja2 templates"""
    
    def __init__(self):
        self.smtp_host = getattr(settings, 'smtp_host', None)
        self.smtp_port = getattr(settings, 'smtp_port', 587)
        self.smtp_user = getattr(settings, 'smtp_user', None)
        self.smtp_password = getattr(settings, 'smtp_password', None)
        self.smtp_from = getattr(settings, 'smtp_from', 'noreply@nukelab.local')
        self.enabled = bool(self.smtp_host)
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an email"""
        if not self.enabled:
            return {"success": False, "error": "SMTP not configured"}
        
        try:
            import aiosmtplib
            
            message = f"""From: {self.smtp_from}
To: {to_email}
Subject: {subject}
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain; charset=utf-8

{text_body or html_body}

--boundary
Content-Type: text/html; charset=utf-8

{html_body}
--boundary--
"""
            
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
            )
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render an email template"""
        templates = {
            "welcome": self._welcome_template,
            "credit_low": self._credit_low_template,
            "server_ready": self._server_ready_template,
            "server_stopped": self._server_stopped_template,
            "maintenance": self._maintenance_template,
        }
        
        template_func = templates.get(template_name)
        if not template_func:
            return f"<html><body><p>{context.get('message', '')}</p></body></html>"
        
        return template_func(context)
    
    def _welcome_template(self, ctx: Dict[str, Any]) -> str:
        return f"""
        <html>
        <body>
            <h1>Welcome to NukeLab!</h1>
            <p>Hello {ctx.get('username', 'there')},</p>
            <p>Your account has been created successfully. You have {ctx.get('credits', 0)} NUKE credits to get started.</p>
            <p>Get started by creating your first server!</p>
        </body>
        </html>
        """
    
    def _credit_low_template(self, ctx: Dict[str, Any]) -> str:
        return f"""
        <html>
        <body>
            <h1>Low NUKE Credits</h1>
            <p>Hello {ctx.get('username', 'there')},</p>
            <p>Your NUKE credit balance is running low: <strong>{ctx.get('balance', 0)} credits</strong>.</p>
            <p>Server: {ctx.get('server_name', 'Unknown')}</p>
            <p>Please top up your credits to avoid automatic server shutdown.</p>
        </body>
        </html>
        """
    
    def _server_ready_template(self, ctx: Dict[str, Any]) -> str:
        return f"""
        <html>
        <body>
            <h1>Server Ready</h1>
            <p>Hello {ctx.get('username', 'there')},</p>
            <p>Your server <strong>{ctx.get('server_name', 'Unknown')}</strong> is now running and ready to use.</p>
            <p>Access URL: <a href="{ctx.get('url', '#')}"\u003e{ctx.get('url', '#')}</a></p>
        </body>
        </html>
        """
    
    def _server_stopped_template(self, ctx: Dict[str, Any]) -> str:
        return f"""
        <html>
        <body>
            <h1>Server Stopped</h1>
            <p>Hello {ctx.get('username', 'there')},</p>
            <p>Your server <strong>{ctx.get('server_name', 'Unknown')}</strong> has been stopped.</p>
            <p>Reason: {ctx.get('reason', 'Unknown')}</p>
        </body>
        </html>
        """
    
    def _maintenance_template(self, ctx: Dict[str, Any]) -> str:
        return f"""
        <html>
        <body>
            <h1>Maintenance Notice</h1>
            <p>Hello {ctx.get('username', 'there')},</p>
            <p>{ctx.get('message', 'The system will undergo maintenance.')}</p>
        </body>
        </html>
        """
