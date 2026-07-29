# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the grouped, permission-scoped search API endpoint."""

import pytest
import pytest_asyncio

from app.api.auth import create_access_token, get_password_hash
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.user import User
from app.models.volume import Volume


@pytest_asyncio.fixture
async def other_user(db_session):
    """Create a second regular user to own resources that must not leak."""
    user = User(
        username="otheruser",
        email="other@example.com",
        password_hash=get_password_hash("otherpass123"),
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def guest_user(db_session):
    """Create a guest user (only servers:read_own and volumes:read_own)."""
    user = User(
        username="guestuser",
        email="guest@example.com",
        password_hash=get_password_hash("guestpass123"),
        role="guest",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def guest_token(guest_user):
    """Generate JWT token for guest user."""
    return create_access_token(data={"sub": guest_user.username, "role": guest_user.role})


class TestSearchScoping:
    """Ownership and permission scoping of search groups."""

    @pytest.mark.asyncio
    async def test_regular_user_sees_only_own_resources(
        self, client, db_session, test_user, user_token, other_user
    ):
        """Regular users see own + member resources; other users' resources must not leak."""
        db_session.add(Server(name="alpha-own-server", user_id=test_user.id, status="running"))
        db_session.add(
            Volume(
                name="alpha-own-vol",
                display_name="Alpha Own Vol",
                owner_id=test_user.id,
                size_bytes=10,
                status="active",
            )
        )
        db_session.add(SharedWorkspace(name="alpha-own-ws", owner_id=test_user.id, is_active=True))

        # Resources owned by someone else.
        db_session.add(Server(name="alpha-other-server", user_id=other_user.id, status="running"))
        db_session.add(
            Volume(
                name="alpha-other-vol",
                display_name="Alpha Other Vol",
                owner_id=other_user.id,
                size_bytes=20,
                status="active",
            )
        )
        db_session.add(
            SharedWorkspace(name="alpha-other-ws", owner_id=other_user.id, is_active=True)
        )

        # Workspace owned by someone else that the user is a member of.
        member_ws = SharedWorkspace(name="alpha-member-ws", owner_id=other_user.id, is_active=True)
        db_session.add(member_ws)
        await db_session.flush()
        db_session.add(
            WorkspaceMember(workspace_id=member_ws.id, user_id=test_user.id, role="read_write")
        )

        db_session.add(
            EnvironmentTemplate(
                name="Alpha Jupyter", slug="alpha-jupyter", image="test:latest", category="notebook"
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/search/",
            params={"q": "alpha"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        assert [s["name"] for s in data["servers"]] == ["alpha-own-server"]
        assert data["servers"][0]["status"] == "running"

        assert [v["name"] for v in data["volumes"]] == ["alpha-own-vol"]
        assert data["volumes"][0]["display_name"] == "Alpha Own Vol"
        assert data["volumes"][0]["size_bytes"] == 10

        assert sorted(w["name"] for w in data["workspaces"]) == [
            "alpha-member-ws",
            "alpha-own-ws",
        ]

        assert [e["slug"] for e in data["environments"]] == ["alpha-jupyter"]
        assert data["environments"][0]["category"] == "notebook"

        # Regular users lack users:read.
        assert "users" not in data

    @pytest.mark.asyncio
    async def test_admin_sees_all_resources(
        self, client, db_session, admin_token, test_user, other_user
    ):
        """Admins (read_all) see resources owned by any user."""
        db_session.add(Server(name="beta-other-server", user_id=other_user.id, status="running"))
        db_session.add(
            Volume(name="beta-other-vol", display_name="Beta Other Vol", owner_id=other_user.id)
        )
        db_session.add(
            SharedWorkspace(name="beta-other-ws", owner_id=other_user.id, is_active=True)
        )
        await db_session.commit()

        response = await client.get(
            "/api/search/",
            params={"q": "beta"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        assert [s["name"] for s in data["servers"]] == ["beta-other-server"]
        assert [v["name"] for v in data["volumes"]] == ["beta-other-vol"]
        assert [w["name"] for w in data["workspaces"]] == ["beta-other-ws"]

    @pytest.mark.asyncio
    async def test_groups_omitted_without_read_permission(
        self, client, db_session, guest_user, guest_token
    ):
        """Groups whose read permission is missing are omitted entirely (never 403)."""
        db_session.add(Server(name="delta-srv", user_id=guest_user.id, status="running"))
        db_session.add(EnvironmentTemplate(name="Delta Env", slug="delta-env", image="test:latest"))
        db_session.add(SharedWorkspace(name="delta-ws", owner_id=guest_user.id, is_active=True))
        await db_session.commit()

        response = await client.get(
            "/api/search/",
            params={"q": "delta"},
            headers={"Authorization": f"Bearer {guest_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        # guest has servers:read_own and volumes:read_own only.
        assert [s["name"] for s in data["servers"]] == ["delta-srv"]
        assert data["volumes"] == []  # permitted group stays present, even when empty
        assert "workspaces" not in data
        assert "environments" not in data  # no ENVIRONMENT_READ
        assert "users" not in data


class TestSearchUsersGroup:
    """The users group mirrors the admin.users page guard (users:read)."""

    @pytest.mark.asyncio
    async def test_users_group_absent_without_users_read(self, client, test_user, user_token):
        response = await client.get(
            "/api/search/",
            params={"q": "test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert "users" not in response.json()

    @pytest.mark.asyncio
    async def test_users_group_present_with_users_read(
        self, client, test_user, support_user, support_token
    ):
        """The support role has users:read (without being admin)."""
        response = await client.get(
            "/api/search/",
            params={"q": "test"},
            headers={"Authorization": f"Bearer {support_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        assert [u["username"] for u in data["users"]] == ["testuser"]
        assert data["users"][0]["email"] == "test@example.com"


class TestSearchValidation:
    """Query parameter validation and limiting."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_422(self, client, user_token):
        response = await client.get(
            "/api/search/",
            params={"q": ""},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_query_returns_422(self, client, user_token):
        response = await client.get(
            "/api/search/",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_out_of_range_returns_422(self, client, user_token):
        for bad_limit in (0, 21):
            response = await client.get(
                "/api/search/",
                params={"q": "test", "limit": bad_limit},
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_caps_group_size(self, client, db_session, test_user, user_token):
        for i in range(7):
            db_session.add(Server(name=f"gamma-srv-{i}", user_id=test_user.id, status="running"))
        await db_session.commit()

        response = await client.get(
            "/api/search/",
            params={"q": "gamma", "limit": 3},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        # Also asserts ordering by name.
        assert [s["name"] for s in response.json()["servers"]] == [
            "gamma-srv-0",
            "gamma-srv-1",
            "gamma-srv-2",
        ]

        # Default limit is 5.
        response = await client.get(
            "/api/search/",
            params={"q": "gamma"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()["servers"]) == 5


class TestSearchGroupParam:
    """The optional group query parameter scopes the response to one group."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("group", ["servers", "volumes", "workspaces", "environments"])
    async def test_group_returns_only_that_group(
        self, client, db_session, test_user, user_token, group
    ):
        db_session.add(Server(name="omega-srv", user_id=test_user.id, status="running"))
        db_session.add(Volume(name="omega-vol", display_name="Omega Vol", owner_id=test_user.id))
        db_session.add(SharedWorkspace(name="omega-ws", owner_id=test_user.id, is_active=True))
        db_session.add(EnvironmentTemplate(name="Omega Env", slug="omega-env", image="test:latest"))
        await db_session.commit()

        response = await client.get(
            "/api/search/",
            params={"q": "omega", "group": group},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert list(data.keys()) == [group]
        assert len(data[group]) == 1

    @pytest.mark.asyncio
    async def test_group_users_returns_only_users(
        self, client, test_user, support_user, support_token
    ):
        """The support role has users:read (without being admin)."""
        response = await client.get(
            "/api/search/",
            params={"q": "test", "group": "users"},
            headers={"Authorization": f"Bearer {support_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert list(data.keys()) == ["users"]
        assert [u["username"] for u in data["users"]] == ["testuser"]

    @pytest.mark.asyncio
    async def test_invalid_group_returns_422(self, client, user_token):
        response = await client.get(
            "/api/search/",
            params={"q": "test", "group": "bogus"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_group_without_permission_returns_200_without_key(
        self, client, test_user, user_token
    ):
        """A requested group is omitted (never 403) when its read permission is missing."""
        response = await client.get(
            "/api/search/",
            params={"q": "test", "group": "users"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert "users" not in response.json()
