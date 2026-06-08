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
            mock_session.post = MagicMock(return_value=mock_response)
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

"""Extended coverage tests for WebhookService error/retry branches."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.webhook_service import WebhookService


def _make_awaitable_context_manager(response_status=200, side_effect=None):
    """Create a mock that works with `async with session.post(...) as response`."""
    mock_response = AsyncMock()
    mock_response.status = response_status
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    # session.post is synchronous in aiohttp — it returns a context manager directly
    mock_post = MagicMock(return_value=mock_response)
    if side_effect:
        mock_post.side_effect = side_effect

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = mock_post
    return mock_session, mock_post


class TestWebhookServiceDispatchRetry:
    """Tests for dispatch retry and error paths."""

    @pytest.mark.asyncio
    async def test_dispatch_retries_on_failure(self):
        """Should retry on transient failures."""
        service = WebhookService(secret="test")

        mock_session, mock_post = _make_awaitable_context_manager(response_status=500)

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value = mock_session
            result = await service.dispatch("https://example.com/hook", "test.event", {"id": 1})

        assert result["success"] is False
        assert result["attempts"] == 3
        assert mock_post.call_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_exception_on_all_retries(self):
        """Should return failure after all retries throw exceptions."""
        service = WebhookService(secret="test")

        mock_session, mock_post = _make_awaitable_context_manager(
            side_effect=Exception("connection refused")
        )

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value = mock_session
            result = await service.dispatch("https://example.com/hook", "test.event", {"id": 1})

        assert result["success"] is False
        assert "connection refused" in result["error"]
        assert result["attempts"] == 3

    @pytest.mark.asyncio
    async def test_dispatch_eventual_success(self):
        """Should succeed on second attempt."""
        service = WebhookService(secret="test")

        fail_response = AsyncMock()
        fail_response.status = 500
        fail_response.__aenter__ = AsyncMock(return_value=fail_response)
        fail_response.__aexit__ = AsyncMock(return_value=False)

        ok_response = AsyncMock()
        ok_response.status = 200
        ok_response.__aenter__ = AsyncMock(return_value=ok_response)
        ok_response.__aexit__ = AsyncMock(return_value=False)

        # session.post is synchronous in aiohttp
        mock_post = MagicMock(side_effect=[fail_response, ok_response])
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = mock_post

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value = mock_session
            result = await service.dispatch("https://example.com/hook", "test.event", {"id": 1}, max_retries=2)

        assert result["success"] is True
        assert result["attempt"] == 2


class TestWebhookServiceDispatchToUserExtended:
    """Tests for dispatch_to_user with mocked db."""

    @pytest.mark.asyncio
    async def test_dispatch_to_user_success(self, db_session, test_user):
        """Should dispatch to user's webhook URL."""
        test_user.preferences = {"webhook_url": "https://example.com/hook"}
        await db_session.commit()

        service = WebhookService(secret="test")
        mock_session, _ = _make_awaitable_context_manager(response_status=200)

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_cls.return_value = mock_session
            result = await service.dispatch_to_user(str(test_user.id), "test.event", {"id": 1}, db=db_session)

        assert result["success"] is True

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
