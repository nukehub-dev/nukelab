"""Tests for Email service and templates."""

import pytest


class TestEmailTemplates:
    """Email template rendering tests."""

    def test_welcome_template(self):
        """Welcome template should render with username and credits."""
        from app.services.email_service import EmailService

        service = EmailService()
        html = service.render_template("welcome", {"username": "testuser", "credits": 100})

        assert "Welcome to NukeLab" in html
        assert "testuser" in html

    def test_credit_low_template(self):
        """Credit low template should render with balance and server name."""
        from app.services.email_service import EmailService

        service = EmailService()
        html = service.render_template(
            "credit_low", {"username": "testuser", "balance": 10, "server_name": "test-server"}
        )

        assert "Low NUKE Credits" in html
        assert "10 credits" in html


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
        html = service.render_template(
            "server_ready",
            {"username": "alice", "server_name": "srv1", "url": "https://example.com/srv1"},
        )
        assert "Server Ready" in html
        assert "srv1" in html
        assert "https://example.com/srv1" in html

    def test_server_stopped_template(self):
        service = EmailService()
        html = service.render_template(
            "server_stopped", {"username": "bob", "server_name": "srv2", "reason": "maintenance"}
        )
        assert "Server Stopped" in html
        assert "srv2" in html
        assert "maintenance" in html

    def test_maintenance_template(self):
        service = EmailService()
        html = service.render_template(
            "maintenance", {"username": "charlie", "message": "Scheduled maintenance at midnight"}
        )
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


"""Extended tests for EmailService send method."""

import pytest
from unittest import mock

from app.services.email_service import EmailService


class TestEmailServiceSendEnabled:
    """Tests for send_email when SMTP is configured."""

    @pytest.fixture
    def email_service(self):
        service = EmailService()
        service.enabled = True
        service.smtp_host = "smtp.test.com"
        service.smtp_port = 587
        service.smtp_user = "user@test.com"
        service.smtp_password = "secret"
        service.smtp_from = "from@test.com"
        service.smtp_from_name = "Test Sender"
        service.use_tls = True
        service.verify_certs = False
        return service

    @pytest.mark.asyncio
    async def test_send_email_success(self, email_service):
        """Should send email successfully with mocked SMTP."""
        with mock.patch("aiosmtplib.SMTP") as mock_smtp_cls:
            mock_smtp = mock.AsyncMock()
            mock_smtp_cls.return_value = mock_smtp

            result = await email_service.send_email(
                to_email="to@test.com",
                subject="Test Subject",
                html_body="<p>Hello</p>",
                text_body="Hello",
            )

        assert result["success"] is True
        mock_smtp.connect.assert_awaited_once()
        mock_smtp.starttls.assert_awaited_once()
        mock_smtp.login.assert_awaited_once()
        mock_smtp.send_message.assert_awaited_once()
        mock_smtp.quit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_email_no_tls(self, email_service):
        """Should not call starttls when TLS is disabled."""
        email_service.use_tls = False

        with mock.patch("aiosmtplib.SMTP") as mock_smtp_cls:
            mock_smtp = mock.AsyncMock()
            mock_smtp_cls.return_value = mock_smtp

            result = await email_service.send_email(
                to_email="to@test.com", subject="Test Subject", html_body="<p>Hello</p>"
            )

        assert result["success"] is True
        mock_smtp.starttls.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_email_no_auth(self, email_service):
        """Should not call login when no credentials."""
        email_service.smtp_user = None
        email_service.smtp_password = None

        with mock.patch("aiosmtplib.SMTP") as mock_smtp_cls:
            mock_smtp = mock.AsyncMock()
            mock_smtp_cls.return_value = mock_smtp

            result = await email_service.send_email(
                to_email="to@test.com", subject="Test Subject", html_body="<p>Hello</p>"
            )

        assert result["success"] is True
        mock_smtp.login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_email_smtp_error(self, email_service):
        """Should return error on SMTP failure."""
        with mock.patch("aiosmtplib.SMTP") as mock_smtp_cls:
            mock_smtp = mock.AsyncMock()
            mock_smtp.connect.side_effect = ConnectionError("SMTP down")
            mock_smtp_cls.return_value = mock_smtp

            result = await email_service.send_email(
                to_email="to@test.com", subject="Test Subject", html_body="<p>Hello</p>"
            )

        assert result["success"] is False
        assert "SMTP down" in result["error"]


class TestEmailServiceProperties:
    """Tests for EmailService initialization."""

    def test_enabled_when_smtp_host_set(self):
        """Should be enabled when smtp_host is configured."""
        with mock.patch("app.services.email_service.settings") as mock_settings:
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = None
            mock_settings.smtp_password = None
            mock_settings.smtp_from = "from@example.com"
            mock_settings.smtp_from_name = "NukeLab"
            mock_settings.smtp_tls = True
            mock_settings.smtp_verify_certs = True

            service = EmailService()
            assert service.enabled is True
            assert service.smtp_host == "smtp.example.com"

    def test_disabled_when_smtp_host_missing(self):
        """Should be disabled when smtp_host is not set."""
        with mock.patch("app.services.email_service.settings") as mock_settings:
            mock_settings.smtp_host = None
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = None
            mock_settings.smtp_password = None
            mock_settings.smtp_from = "from@example.com"
            mock_settings.smtp_from_name = "NukeLab"
            mock_settings.smtp_tls = True
            mock_settings.smtp_verify_certs = True

            service = EmailService()
            assert service.enabled is False
