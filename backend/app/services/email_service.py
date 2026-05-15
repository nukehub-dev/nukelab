"""
Email notification service with SMTP and templates.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from app.config import settings


class EmailService:
    """Email service with Jinja2 templates"""
    
    def __init__(self):
        self.smtp_host = settings.smtp_host or None
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user or None
        self.smtp_password = settings.smtp_password or None
        self.smtp_from = settings.smtp_from
        self.smtp_from_name = settings.smtp_from_name
        self.use_tls = settings.smtp_tls
        self.verify_certs = settings.smtp_verify_certs
        self.enabled = bool(self.smtp_host)
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an email using explicit SMTP control"""
        if not self.enabled:
            return {"success": False, "error": "SMTP not configured"}

        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import aiosmtplib

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.smtp_from_name} <{self.smtp_from}>"
            msg['To'] = to_email

            msg.attach(MIMEText(text_body or html_body, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            # Explicit SMTP control to avoid auto-TLS issues on port 587
            smtp = aiosmtplib.SMTP(
                hostname=self.smtp_host,
                port=self.smtp_port,
                start_tls=False,
                validate_certs=self.verify_certs,
            )
            await smtp.connect()
            if self.use_tls:
                await smtp.starttls(validate_certs=self.verify_certs)
            if self.smtp_user and self.smtp_password:
                await smtp.login(self.smtp_user, self.smtp_password)
            await smtp.send_message(msg)
            await smtp.quit()

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
