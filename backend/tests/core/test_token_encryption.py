"""Tests for app.core.token_encryption."""

from app.core.token_encryption import decrypt_token, encrypt_token


class TestTokenEncryption:
    def test_roundtrip(self):
        original = "super-secret-token-123"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)
        assert decrypted == original

    def test_different_tokens_different_ciphertexts(self):
        e1 = encrypt_token("token-a")
        e2 = encrypt_token("token-b")
        assert e1 != e2

    def test_empty_string(self):
        assert encrypt_token("") == ""
        assert decrypt_token("") == ""

    def test_unicode_token(self):
        original = "日本語トークン"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)
        assert decrypted == original
