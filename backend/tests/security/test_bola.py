"""Security regression tests for Broken Object Level Authorization (BOLA / IDOR).

These tests verify that users cannot access or modify resources belonging to
other users unless they have explicit permissions.
"""

import pytest
from httpx import AsyncClient

from app.models.server import Server
from app.models.shared_workspace import SharedWorkspace as Workspace
from app.models.volume import Volume


async def _create_server(db_session, user, name="victim-server", status="stopped"):
    """Helper to create a server owned by a specific user."""
    server = Server(
        name=name,
        user_id=user.id,
        status=status,
        allocated_cpu=1,
        allocated_memory="1g",
        allocated_disk="10g",
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


async def _create_volume(db_session, user, name="victim-volume"):
    """Helper to create a volume owned by a specific user."""
    volume = Volume(
        name=name,
        display_name="Victim Volume",
        owner_id=user.id,
        status="active",
    )
    db_session.add(volume)
    await db_session.commit()
    await db_session.refresh(volume)
    return volume


async def _create_workspace(db_session, owner, name="victim-workspace"):
    """Helper to create a workspace owned by a specific user."""
    workspace = Workspace(
        name=name,
        description="Victim Workspace",
        owner_id=owner.id,
        is_active=True,
    )
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    return workspace


class TestServerBOLA:
    """BOLA tests for server endpoints."""

    @pytest.mark.asyncio
    async def test_user_cannot_read_other_user_server(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to read User B's server details."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimuser",
            email="victim@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="User",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        server = await _create_server(db_session, victim)

        response = await client.get(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_start_other_user_server(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to start User B's server."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimuser2",
            email="victim2@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="User",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        server = await _create_server(db_session, victim)

        response = await client.post(
            f"/api/servers/{server.id}/start",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_delete_other_user_server(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to delete User B's server."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimuser3",
            email="victim3@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="User",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        server = await _create_server(db_session, victim)

        response = await client.delete(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_admin_can_read_other_user_server(
        self, client: AsyncClient, admin_user, admin_token, db_session
    ):
        """Admin should be able to read any server with servers:read_all."""
        server = await _create_server(db_session, admin_user, name="admin-owned")

        response = await client.get(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )


class TestVolumeBOLA:
    """BOLA tests for volume endpoints."""

    @pytest.mark.asyncio
    async def test_user_cannot_read_other_user_volume(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to read User B's volume."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimvol",
            email="victimvol@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Volume",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        volume = await _create_volume(db_session, victim)

        response = await client.get(
            f"/api/volumes/{volume.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_update_other_user_volume(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to update User B's volume."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimvol2",
            email="victimvol2@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Volume",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        volume = await _create_volume(db_session, victim)

        response = await client.put(
            f"/api/volumes/{volume.id}",
            json={"display_name": "Hacked Volume", "max_size_bytes": 10737418240},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_delete_other_user_volume(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to delete User B's volume."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimvol3",
            email="victimvol3@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Volume",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        volume = await _create_volume(db_session, victim)

        response = await client.delete(
            f"/api/volumes/{volume.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )


class TestWorkspaceBOLA:
    """BOLA tests for workspace endpoints."""

    @pytest.mark.asyncio
    async def test_user_cannot_read_unrelated_workspace(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to read a workspace they are not a member of."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimws",
            email="victimws@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Workspace",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        workspace = await _create_workspace(db_session, victim)

        response = await client.get(
            f"/api/workspaces/{workspace.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_update_unrelated_workspace(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to update a workspace they do not own."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimws2",
            email="victimws2@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Workspace",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        workspace = await _create_workspace(db_session, victim)

        response = await client.put(
            f"/api/workspaces/{workspace.id}",
            json={"display_name": "Hacked Workspace"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )


class TestCreditBOLA:
    """BOLA tests for credit/NUKE transaction endpoints."""

    @pytest.mark.asyncio
    async def test_user_credit_history_does_not_leak_other_user_transactions(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A's credit history should not include User B's transactions."""
        from app.models.credit_transaction import CreditTransaction
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimcredit",
            email="victimcredit@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Credit",
            role="user",
            is_active=True,
            is_verified=True,
            nuke_balance=500,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        # Create a transaction for the victim
        victim_tx = CreditTransaction(
            user_id=victim.id,
            amount=100,
            balance_after=600,
            type="admin_grant",
            description="victim transaction",
            actor_id=victim.id,
        )
        db_session.add(victim_tx)
        await db_session.commit()

        response = await client.get(
            "/api/credits/history",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        transactions = data.get("transactions", [])
        for tx in transactions:
            assert str(tx.get("user_id")) != str(victim.id), (
                "Leaked victim transaction in credit history"
            )


class TestUserProfileBOLA:
    """BOLA tests for user profile endpoints."""

    @pytest.mark.asyncio
    async def test_user_cannot_update_other_user_profile(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to update User B's profile."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimprofile",
            email="victimprofile@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Profile",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        response = await client.put(
            f"/api/users/{victim.id}",
            json={"first_name": "Hacked"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_user_cannot_read_other_user_full_profile(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User A should not be able to read sensitive fields of User B's profile."""
        from tests.conftest import User, get_password_hash

        victim = User(
            username="victimprofile2",
            email="victimprofile2@example.com",
            password_hash=get_password_hash("victimpass123"),
            first_name="Victim",
            last_name="Profile",
            role="user",
            is_active=True,
            is_verified=True,
        )
        db_session.add(victim)
        await db_session.commit()
        await db_session.refresh(victim)

        response = await client.get(
            f"/api/users/{victim.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )
