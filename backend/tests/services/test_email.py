"""Tests for Email service and templates."""

import pytest


class TestEmailTemplates:
    """Email template rendering tests."""

    def test_welcome_template(self):
        """Welcome template should render with username and credits."""
        from app.services.email_service import EmailService

        service = EmailService()
        html = service.render_template("welcome", {
            "username": "testuser",
            "credits": 100
        })

        assert "Welcome to NukeLab" in html
        assert "testuser" in html

    def test_credit_low_template(self):
        """Credit low template should render with balance and server name."""
        from app.services.email_service import EmailService

        service = EmailService()
        html = service.render_template("credit_low", {
            "username": "testuser",
            "balance": 10,
            "server_name": "test-server"
        })

        assert "Low NUKE Credits" in html
        assert "10 credits" in html
