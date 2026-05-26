"""Tests for admin volume management endpoints."""

import pytest
from httpx import AsyncClient


class TestAdminVolumeList:
    """Admin volume listing tests."""

    @pytest.mark.asyncio
    async def test_admin_can_list_all_volumes(self, client: AsyncClient, test_user, admin_user, admin_token):
        """Admin should see all volumes."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create volumes via API
        resp1 = await client.post("/api/volumes/", json={
            "name": "vol_alpha",
            "display_name": "Alpha Volume",
            "description": "First volume"
        }, headers=headers)
        assert resp1.status_code == 201
        resp2 = await client.post("/api/volumes/", json={
            "name": "vol_beta",
            "display_name": "Beta Volume",
            "description": "Second volume"
        }, headers=headers)
        assert resp2.status_code == 201

        response = await client.get("/api/admin/volumes", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "volumes" in data
        assert "pagination" in data
        assert len(data["volumes"]) >= 2
        names = [v["display_name"] for v in data["volumes"]]
        assert "Alpha Volume" in names
        assert "Beta Volume" in names

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_volumes(self, client: AsyncClient, test_user, user_token):
        """Regular user should get 403 on admin volume list."""
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.get("/api/admin/volumes", headers=headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_search_volumes(self, client: AsyncClient, admin_user, admin_token):
        """Admin should be able to search volumes by name."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp1 = await client.post("/api/volumes/", json={
            "name": "searchable_alpha",
            "display_name": "Searchable Alpha",
        }, headers=headers)
        assert resp1.status_code == 201
        resp2 = await client.post("/api/volumes/", json={
            "name": "searchable_beta",
            "display_name": "Searchable Beta",
        }, headers=headers)
        assert resp2.status_code == 201

        response = await client.get("/api/admin/volumes?search=Alpha", headers=headers)
        assert response.status_code == 200
        data = response.json()
        names = [v["display_name"] for v in data["volumes"]]
        assert "Searchable Alpha" in names
        assert "Searchable Beta" not in names

    @pytest.mark.asyncio
    async def test_admin_filter_by_status(self, client: AsyncClient, admin_user, admin_token):
        """Admin should be able to filter volumes by status."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.post("/api/volumes/", json={
            "name": "status_vol",
            "display_name": "Status Volume",
        }, headers=headers)
        assert resp.status_code == 201

        response = await client.get("/api/admin/volumes?status=active", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert all(v["status"] == "active" for v in data["volumes"])

    @pytest.mark.asyncio
    async def test_admin_filter_by_visibility(self, client: AsyncClient, admin_user, admin_token):
        """Admin should be able to filter volumes by visibility."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.post("/api/volumes/", json={
            "name": "vis_private",
            "display_name": "Private Volume",
            "visibility": "private"
        }, headers=headers)
        assert resp.status_code == 201

        response = await client.get("/api/admin/volumes?visibility=private", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert all(v["visibility"] == "private" for v in data["volumes"])


class TestAdminVolumeDetail:
    """Admin volume detail tests."""

    @pytest.mark.asyncio
    async def test_admin_can_get_volume_details(self, client: AsyncClient, admin_user, admin_token):
        """Admin should get volume details."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "detail_vol",
            "display_name": "Detail Volume",
        }, headers=headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        response = await client.get(f"/api/admin/volumes/{vol_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "volume" in data
        assert data["volume"]["display_name"] == "Detail Volume"

    @pytest.mark.asyncio
    async def test_admin_get_nonexistent_volume(self, client: AsyncClient, admin_user, admin_token):
        """Admin should get 404 for nonexistent volume."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = await client.get("/api/admin/volumes/00000000-0000-0000-0000-000000000000", headers=headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_get_volume_details(self, client: AsyncClient, test_user, user_token):
        """Regular user should get 403."""
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.get("/api/admin/volumes/00000000-0000-0000-0000-000000000000", headers=headers)
        assert response.status_code == 403


class TestAdminVolumeUpdate:
    """Admin volume update tests."""

    @pytest.mark.asyncio
    async def test_admin_can_update_volume(self, client: AsyncClient, admin_user, admin_token):
        """Admin with VOLUMES_MANAGE should update any volume."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "update_vol",
            "display_name": "Update Volume",
            "description": "Old desc",
            "visibility": "private"
        }, headers=headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        response = await client.put(f"/api/admin/volumes/{vol_id}", json={
            "display_name": "Updated Name",
            "description": "New desc",
            "visibility": "public",
            "status": "archived",
            "max_size_bytes": 1073741824
        }, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["volume"]["display_name"] == "Updated Name"
        assert data["volume"]["description"] == "New desc"
        assert data["volume"]["visibility"] == "public"
        assert data["volume"]["status"] == "archived"
        assert data["volume"]["max_size_bytes"] == 1073741824

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_volume(self, client: AsyncClient, test_user, user_token, admin_user, admin_token):
        """Regular user should get 403."""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "protected_vol",
            "display_name": "Protected Volume",
        }, headers=admin_headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        response = await client.put(f"/api/admin/volumes/{vol_id}", json={"display_name": "Hacked"}, headers=user_headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_cannot_shrink_volume_below_used_size(self, client: AsyncClient, admin_user, admin_token, db_session):
        """Admin should get 400 when trying to set max_size below current size_bytes."""
        from app.services.volume_service import VolumeService

        headers = {"Authorization": f"Bearer {admin_token}"}
        service = VolumeService(db_session)

        volume = await service.create_volume(
            name="admin-shrink-test",
            display_name="Admin Shrink Test",
            owner_id=str(admin_user.id),
            max_size_bytes=50 * 1024 * 1024 * 1024,
        )
        volume.size_bytes = 10 * 1024 * 1024 * 1024  # 10 GB used
        await db_session.commit()

        response = await client.put(f"/api/admin/volumes/{volume.id}", headers=headers, json={
            "max_size_bytes": 5 * 1024 * 1024 * 1024,  # Try to shrink to 5 GB
        })
        assert response.status_code == 400
        assert "cannot set volume limit" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_admin_can_increase_volume_max_size(self, client: AsyncClient, admin_user, admin_token, db_session):
        """Admin should be able to increase volume max_size."""
        from app.services.volume_service import VolumeService

        headers = {"Authorization": f"Bearer {admin_token}"}
        service = VolumeService(db_session)

        volume = await service.create_volume(
            name="admin-grow-test",
            display_name="Admin Grow Test",
            owner_id=str(admin_user.id),
            max_size_bytes=10 * 1024 * 1024 * 1024,
        )
        volume.size_bytes = 2 * 1024 * 1024 * 1024
        await db_session.commit()

        response = await client.put(f"/api/admin/volumes/{volume.id}", headers=headers, json={
            "max_size_bytes": 100 * 1024 * 1024 * 1024,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["volume"]["max_size_bytes"] == 100 * 1024 * 1024 * 1024


class TestAdminVolumeDelete:
    """Admin volume delete tests."""

    @pytest.mark.asyncio
    async def test_admin_can_delete_volume(self, client: AsyncClient, admin_user, admin_token):
        """Admin with VOLUMES_MANAGE should delete any volume."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "delete_vol",
            "display_name": "Delete Volume",
        }, headers=headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        response = await client.delete(f"/api/admin/volumes/{vol_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify it's gone
        get_resp = await client.get(f"/api/admin/volumes/{vol_id}", headers=headers)
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete_volume(self, client: AsyncClient, test_user, user_token, admin_user, admin_token):
        """Regular user should get 403."""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "protected_del_vol",
            "display_name": "Protected Volume",
        }, headers=admin_headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        response = await client.delete(f"/api/admin/volumes/{vol_id}", headers=user_headers)
        assert response.status_code == 403


class TestBulkVolumeActions:
    """Bulk volume action tests."""

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, client: AsyncClient, admin_token):
        """Bulk endpoint should reject unknown actions."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid_action", "volume_ids": ["123", "456"]}
        )
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_delete_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'delete' as a valid action."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "delete", "volume_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_archive_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'archive' as a valid action."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "archive", "volume_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_activate_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'activate' as a valid action."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "activate", "volume_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_non_admin_cannot_bulk_action(self, client: AsyncClient, user_token):
        """Regular user should get 403 on volume bulk action."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "delete", "volume_ids": []}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_bulk_delete_volumes(self, client: AsyncClient, admin_token):
        """Admin should be able to bulk delete volumes."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp1 = await client.post("/api/volumes/", json={
            "name": "bulk_del_vol_1",
            "display_name": "Bulk Delete Volume 1",
        }, headers=headers)
        assert create_resp1.status_code == 201
        vol_id1 = create_resp1.json()["id"]

        create_resp2 = await client.post("/api/volumes/", json={
            "name": "bulk_del_vol_2",
            "display_name": "Bulk Delete Volume 2",
        }, headers=headers)
        assert create_resp2.status_code == 201
        vol_id2 = create_resp2.json()["id"]

        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers=headers,
            json={"action": "delete", "volume_ids": [vol_id1, vol_id2]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "delete"
        assert vol_id1 in data["results"]["success"]
        assert vol_id2 in data["results"]["success"]

        # Verify they're gone
        get_resp1 = await client.get(f"/api/admin/volumes/{vol_id1}", headers=headers)
        assert get_resp1.status_code == 404
        get_resp2 = await client.get(f"/api/admin/volumes/{vol_id2}", headers=headers)
        assert get_resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_can_bulk_archive_activate_volumes(self, client: AsyncClient, admin_token):
        """Admin should be able to bulk archive and activate volumes."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/volumes/", json={
            "name": "bulk_toggle_vol",
            "display_name": "Bulk Toggle Volume",
        }, headers=headers)
        assert create_resp.status_code == 201
        vol_id = create_resp.json()["id"]

        # Archive
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers=headers,
            json={"action": "archive", "volume_ids": [vol_id]}
        )
        assert response.status_code == 200
        data = response.json()
        assert vol_id in data["results"]["success"]

        # Verify archived
        get_resp = await client.get(f"/api/admin/volumes/{vol_id}", headers=headers)
        assert get_resp.json()["volume"]["status"] == "archived"

        # Activate
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers=headers,
            json={"action": "activate", "volume_ids": [vol_id]}
        )
        assert response.status_code == 200
        data = response.json()
        assert vol_id in data["results"]["success"]

        # Verify activated
        get_resp = await client.get(f"/api/admin/volumes/{vol_id}", headers=headers)
        assert get_resp.json()["volume"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_api_token_rejected_for_bulk_volume_action(self, client: AsyncClient, admin_user, db_session):
        """API token authentication should be rejected for volume bulk actions (JWT only)."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)

        token = ApiToken(
            user_id=admin_user.id,
            name="Admin API Token",
            token_hash=token_hash,
            token_prefix=raw_token[:16],
            scopes=["servers:read"],
            is_active=True,
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"action": "delete", "volume_ids": []}
        )
        assert response.status_code == 403
        assert "JWT authentication required" in response.json()["detail"]
