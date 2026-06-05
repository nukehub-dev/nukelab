"""Tests for WebhookService business logic."""

import pytest
import json
import hmac
import hashlib
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.webhook_service import WebhookService


def _mock_aiohttp_session(response_status=200, side_effect=None):
    """Helper to create a mocked aiohttp ClientSession."""
    mock_response = AsyncMock()
    mock_response.status = response_status
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_post = AsyncMock(return_value=mock_response)
    if side_effect:
        mock_post.side_effect = side_effect

    mock_session = MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return mock_session


class TestWebhookServiceSign:
    """Tests for _sign_payload."""

    def test_sign_payload_consistency(self):
        """Same payload should produce same signature."""
        service = WebhookService(secret="test-secret")
        payload = {"event": "test", "data": {"id": 1}}
        sig1 = service._sign_payload(payload)
        sig2 = service._sign_payload(payload)
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex

    def test_sign_payload_different_secrets(self):
        """Different secrets should produce different signatures."""
        service1 = WebhookService(secret="secret1")
        service2 = WebhookService(secret="secret2")
        payload = {"event": "test"}
        assert service1._sign_payload(payload) != service2._sign_payload(payload)

    def test_sign_payload_hmac_verification(self):
        """Signature should be verifiable with HMAC."""
        secret = "my-secret"
        service = WebhookService(secret=secret)
        payload = {"event": "test", "timestamp": "2024-01-01T00:00:00"}
        signature = service._sign_payload(payload)

        expected = hmac.new(
            secret.encode(),
            json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(),
            hashlib.sha256
        ).hexdigest()
        assert signature == expected


class TestWebhookServiceDispatch:
    """Tests for dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_returns_dict(self):
        """dispatch should return a dict result."""
        service = WebhookService(secret="test")
        # Patch the internal ClientSession usage to avoid real network calls
        with patch('aiohttp.ClientSession') as mock_cls:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_session

            result = await service.dispatch("https://example.com/hook", "test.event", {"id": 1})

        assert isinstance(result, dict)
        assert "success" in result


class TestWebhookServiceDispatchToUser:
    """Tests for dispatch_to_user."""

    @pytest.mark.asyncio
    async def test_dispatch_to_user_no_db(self):
        """Should fail when no db provided."""
        service = WebhookService(secret="test")
        result = await service.dispatch_to_user("user-1", "test.event", {})
        assert result["success"] is False
        assert "No database session" in result["error"]

    @pytest.mark.asyncio
    async def test_dispatch_to_user_no_webhook_url(self, db_session, test_user):
        """Should fail when user has no webhook URL."""
        service = WebhookService(secret="test")
        result = await service.dispatch_to_user(str(test_user.id), "test.event", {}, db=db_session)
        assert result["success"] is False
        assert "webhook" in result["error"].lower() or "preferences" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_dispatch_to_user_not_found(self, db_session):
        """Should fail when user not found."""
        service = WebhookService(secret="test")
        import uuid as uuid_mod
        result = await service.dispatch_to_user(str(uuid_mod.uuid4()), "test.event", {}, db=db_session)
        assert result["success"] is False
        assert "not found" in result["error"].lower()
