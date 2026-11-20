# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for server create endpoint happy paths."""

import uuid as uuid_mod
from unittest import mock

import pytest
import pytest_asyncio

from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.volume import Volume


@pytest_asyncio.fixture
async def test_plan_env(db_session):
    """Create a plan and environment for server creation."""
    import uuid

    plan = ServerPlan(
        id=uuid.uuid4(),
        name=f"test-plan-{uuid.uuid4().hex[:8]}",
        slug=f"test-plan-{uuid.uuid4().hex[:8]}",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="10g",
        cost_per_hour=0,
        is_active=True,
        is_public=True,
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(
        id=uuid.uuid4(),
        name=f"test-env-{uuid.uuid4().hex[:8]}",
        slug=f"test-env-{uuid.uuid4().hex[:8]}",
        image="test-image",
    )
    db_session.add_all([plan, env])
    await db_session.commit()
    return plan, env


class TestCreateServerHappyPaths:
    """Happy path tests for POST /api/servers/."""

    @pytest.mark.asyncio
    async def test_create_server_basic(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Create a server with minimal payload."""
        plan, env = test_plan_env

        mock_server = Server(
            id=uuid_mod.uuid4(),
            name="new-server",
            user_id=test_user.id,
            environment_id=env.id,
            container_id="container-new",
            image=env.image,
            volume_id=None,
            status="running",
            allocated_cpu=plan.cpu_limit,
            allocated_memory=plan.memory_limit,
            allocated_disk=plan.disk_limit,
            external_url="http://test/url",
        )

        # Patch services at their source modules since they're imported locally
        with mock.patch("app.api.servers.spawner.spawn", return_value=mock_server):
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
                mock_quota = mock_quota_cls.return_value
                mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                mock_quota.check_volume_creation_allowed = mock.AsyncMock(
                    return_value={"allowed": True}
                )
                mock_quota.increment_usage = mock.AsyncMock()
                with mock.patch(
                    "app.services.resource_pool_service.ResourcePoolService"
                ) as mock_pool_cls:
                    mock_pool = mock_pool_cls.return_value
                    mock_pool.can_fit = mock.AsyncMock(return_value=True)
                    with mock.patch("app.services.credit_service.CreditService") as mock_credit_cls:
                        mock_credit = mock_credit_cls.return_value
                        mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=True)
                        with mock.patch(
                            "app.services.volume_service.VolumeService"
                        ) as mock_vol_cls:
                            mock_vol = mock_vol_cls.return_value

                            async def create_vol_side_effect(
                                *, name, display_name, owner_id, max_size_bytes
                            ):
                                vol = Volume(
                                    name=name,
                                    display_name=display_name,
                                    owner_id=owner_id,
                                    size_bytes=max_size_bytes or 1000,
                                )
                                db_session.add(vol)
                                await db_session.commit()
                                await db_session.refresh(vol)
                                return vol

                            mock_vol.create_volume = mock.AsyncMock(
                                side_effect=create_vol_side_effect
                            )
                            mock_vol.record_mount = mock.AsyncMock()
                            mock_vol.mark_home_volume = mock.AsyncMock()
                            mock_vol.check_quota = mock.AsyncMock(return_value={"allowed": True})
                            mock_vol.check_aggregate_quota = mock.AsyncMock(
                                return_value={"allowed": True}
                            )
                            mock_vol.check_volumes_quota = mock.AsyncMock(
                                return_value={"allowed": True}
                            )
                            mock_vol._parse_memory = mock.Mock(return_value=10737418240)
                            with mock.patch(
                                "app.services.volume_access_service.VolumeAccessService"
                            ) as mock_access_cls:
                                mock_access = mock_access_cls.return_value
                                mock_access.can_access_volume = mock.AsyncMock(return_value=True)

                                response = await client.post(
                                    "/api/servers/",
                                    headers={"Authorization": f"Bearer {user_token}"},
                                    json={
                                        "name": "new-server",
                                        "plan_id": str(plan.id),
                                        "environment_id": str(env.id),
                                    },
                                )

        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()
        assert data["name"] == "new-server"
        assert data["status"] == "running"


class TestCreateServerEnvironmentVisibility:
    """Users cannot spawn servers with private or inactive environments."""

    @pytest.mark.asyncio
    async def test_create_server_private_env_forbidden(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Spawn with a private environment returns 403 for regular users."""
        plan, _ = test_plan_env
        private_env = EnvironmentTemplate(
            id=uuid_mod.uuid4(),
            name="priv-env",
            slug=f"priv-env-{uuid_mod.uuid4().hex[:8]}",
            image="test-image",
            is_public=False,
        )
        db_session.add(private_env)
        await db_session.commit()

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "priv-env-server",
                "plan_id": str(plan.id),
                "environment_id": str(private_env.id),
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_server_inactive_env_forbidden(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Spawn with an inactive environment returns 403."""
        plan, _ = test_plan_env
        inactive_env = EnvironmentTemplate(
            id=uuid_mod.uuid4(),
            name="inactive-env",
            slug=f"inactive-env-{uuid_mod.uuid4().hex[:8]}",
            image="test-image",
            is_active=False,
        )
        db_session.add(inactive_env)
        await db_session.commit()

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "inactive-env-server",
                "plan_id": str(plan.id),
                "environment_id": str(inactive_env.id),
            },
        )
        assert response.status_code == 403


class TestCreateServerDuplicateName:
    """Server names must be unique per user (gateway path + Docker names)."""

    @pytest.mark.asyncio
    async def test_create_server_duplicate_name_rejected(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Creating a second server with an existing name returns 409."""
        plan, env = test_plan_env
        existing = Server(name="dup-server", user_id=test_user.id, status="stopped")
        db_session.add(existing)
        await db_session.commit()

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "dup-server",
                "plan_id": str(plan.id),
                "environment_id": str(env.id),
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "request_already_exists"
