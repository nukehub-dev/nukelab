"""Tests for Bulk Operations API endpoints."""

import pytest


class TestBulkServerActions:
    """Bulk server operation validation tests."""

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, client, admin_token):
        """Bulk endpoint should reject unknown actions."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "invalid_action",
                "server_ids": ["123", "456"]
            }
        )
        
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_start_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'start' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "start",
                "server_ids": []
            }
        )
        
        # Should not be 400 (invalid action), may be 200 or 422 for empty list
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_stop_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'stop' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "stop",
                "server_ids": []
            }
        )
        
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_restart_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'restart' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "restart",
                "server_ids": []
            }
        )
        
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_delete_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'delete' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "delete",
                "server_ids": []
            }
        )
        
        assert response.status_code != 400
