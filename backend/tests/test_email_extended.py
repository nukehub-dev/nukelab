"""Extended tests for EmailService (all templates, disabled state)."""

import pytest
from unittest import mock

from app.services.email_service import EmailService


class TestEmailServiceSend:
    """Tests for send_email method."""

    @pytest.mark.asyncio
    async def test_send_email_disabled(self):
        """When SMTP is not configured, send_email should return error."""
        service = EmailService()
        service.enabled = False
        result = await service.send_email("to@test.com", "Subject", "<p>html</p>")
        assert result["success"] is False
        assert "SMTP not configured" in result["error"]


class TestEmailServiceTemplates:
    """Tests for all email templates."""

    def test_server_ready_template(self):
        service = EmailService()
        html = service.render_template("server_ready", {
            "username": "alice",
            "server_name": "srv1",
            "url": "https://example.com/srv1"
        })
        assert "Server Ready" in html
        assert "srv1" in html
        assert "https://example.com/srv1" in html

    def test_server_stopped_template(self):
        service = EmailService()
        html = service.render_template("server_stopped", {
            "username": "bob",
            "server_name": "srv2",
            "reason": "maintenance"
        })
        assert "Server Stopped" in html
        assert "srv2" in html
        assert "maintenance" in html

    def test_maintenance_template(self):
        service = EmailService()
        html = service.render_template("maintenance", {
            "username": "charlie",
            "message": "Scheduled maintenance at midnight"
        })
        assert "Maintenance Notice" in html
        assert "Scheduled maintenance" in html

    def test_unknown_template_fallback(self):
        service = EmailService()
        html = service.render_template("unknown_template", {"message": "hello"})
        assert "hello" in html

    def test_unknown_template_no_message(self):
        service = EmailService()
        html = service.render_template("nonexistent", {})
        assert "<html>" in html
