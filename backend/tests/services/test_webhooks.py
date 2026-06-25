"""Tests for Webhook service."""


class TestWebhookSigning:
    """Webhook HMAC signature tests."""

    def test_sign_payload_consistency(self):
        """Same payload should produce identical signatures."""
        from app.services.webhook_service import WebhookService

        service = WebhookService(secret="test-secret")
        payload = {"event": "test", "data": {"id": "123"}}

        sig1 = service._sign_payload(payload)
        sig2 = service._sign_payload(payload)

        assert sig1 == sig2
        assert len(sig1) == 64

    def test_different_payloads_different_signatures(self):
        """Different payloads should produce different signatures."""
        from app.services.webhook_service import WebhookService

        service = WebhookService(secret="test-secret")

        sig1 = service._sign_payload({"a": 1})
        sig2 = service._sign_payload({"a": 2})

        assert sig1 != sig2
