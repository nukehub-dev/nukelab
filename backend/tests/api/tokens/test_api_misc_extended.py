"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server

class TestTokensAPI:
    """Tests for API token endpoints."""

    @pytest.mark.asyncio
    async def test_get_token_not_found(self, client, user_token):
        """Getting non-existent token should 404."""
        response = await client.get(
            "/api/tokens/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, client, user_token):
        """Revoking non-existent token should 404."""
        response = await client.delete(
            "/api/tokens/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_token_not_found(self, client, user_token):
        """Permanently deleting non-existent token should 404."""
        response = await client.delete(
            "/api/tokens/00000000-0000-0000-0000-000000000000/permanent",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_regenerate_token_not_found(self, client, user_token):
        """Regenerating non-existent token should 404."""
        response = await client.post(
            "/api/tokens/00000000-0000-0000-0000-000000000000/regenerate",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_token_usage_not_found(self, client, user_token):
        """Getting usage for non-existent token should 404."""
        response = await client.get(
            "/api/tokens/00000000-0000-0000-0000-000000000000/usage",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_token_invalid_scope(self, client, user_token):
        """Creating token with invalid scope should 422."""
        response = await client.post(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "test", "scopes": ["invalid:scope"]}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_tokens(self, client, user_token):
        """Should list user's tokens."""
        response = await client.get(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)



