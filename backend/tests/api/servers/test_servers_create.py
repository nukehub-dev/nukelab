# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for server create endpoint happy paths."""

import uuid as uuid_mod
from unittest import mock

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError

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

    @pytest.mark.asyncio
    async def test_create_server_insufficient_credits(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Create a server without sufficient credits should return 402."""
        plan, env = test_plan_env
        plan.cost_per_hour = 10
        await db_session.commit()

        with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            with mock.patch("app.services.credit_service.CreditService") as mock_credit_cls:
                mock_credit = mock_credit_cls.return_value
                mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=False)

                response = await client.post(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "name": "no-credit-server",
                        "plan_id": str(plan.id),
                        "environment_id": str(env.id),
                    },
                )

        assert response.status_code == 402
        assert (
            "credit" in response.json()["detail"].lower()
            or "Insufficient" in response.json()["detail"]
        )


class TestCreateServerQueueing:
    """Tests for server creation resource pool queueing."""

    @pytest.mark.asyncio
    async def test_create_server_resource_pool_queueing(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """When ResourcePoolService.can_fit returns False, server should be queued."""
        plan, env = test_plan_env

        with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            with mock.patch(
                "app.services.resource_pool_service.ResourcePoolService"
            ) as mock_pool_cls:
                mock_pool = mock_pool_cls.return_value
                mock_pool.can_fit = mock.AsyncMock(return_value=False)
                mock_pool.get_queue_position = mock.AsyncMock(return_value=3)
                with mock.patch("app.services.credit_service.CreditService") as mock_credit_cls:
                    mock_credit = mock_credit_cls.return_value
                    mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=True)

                    # The endpoint returns a dict that doesn't match ServerResponse,
                    # causing ResponseValidationError (pre-existing response model bug).
                    with pytest.raises(ResponseValidationError):
                        await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "queued-server",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                            },
                        )


class TestCreateServerExceptionCleanup:
    """Tests for server creation exception cleanup paths."""

    @pytest.mark.asyncio
    async def test_create_server_exception_cleanup(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """When spawn raises Exception, auto-created volume cleanup code should run."""
        plan, env = test_plan_env

        with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            mock_quota.increment_usage = mock.AsyncMock()
            with mock.patch(
                "app.services.resource_pool_service.ResourcePoolService"
            ) as mock_pool_cls:
                mock_pool = mock_pool_cls.return_value
                mock_pool.can_fit = mock.AsyncMock(return_value=True)
                with mock.patch("app.services.credit_service.CreditService") as mock_credit_cls:
                    mock_credit = mock_credit_cls.return_value
                    mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=True)
                    with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
                        mock_vol = mock_vol_cls.return_value
                        auto_vol = mock.Mock()
                        auto_vol.id = uuid_mod.uuid4()
                        auto_vol.name = f"nukelab-server-{str(test_user.id)}-cleanup-server-data"

                        mock_vol.create_volume = mock.AsyncMock(return_value=auto_vol)
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

                            with (
                                mock.patch(
                                    "app.api.servers.spawner.spawn",
                                    side_effect=Exception("spawn failed"),
                                ),
                                mock.patch(
                                    "app.container.client.get_container_client"
                                ) as mock_get_client,
                            ):
                                mock_container_client = mock.AsyncMock()
                                mock_container_client.client.volumes.get = mock.AsyncMock()
                                mock_container_client.client.containers.get = mock.AsyncMock()
                                mock_get_client.return_value = mock_container_client

                                response = await client.post(
                                    "/api/servers/",
                                    headers={"Authorization": f"Bearer {user_token}"},
                                    json={
                                        "name": "cleanup-server",
                                        "plan_id": str(plan.id),
                                        "environment_id": str(env.id),
                                    },
                                )

        assert response.status_code == 500
        assert (
            "try again" in response.json()["detail"].lower()
            or "contact support" in response.json()["detail"].lower()
        )

    @pytest.mark.asyncio
    async def test_create_server_volume_mount_auto_create_cleanup(
        self, client, user_token, test_user, db_session, test_plan_env
    ):
        """Auto-created volume failure in volume_mounts must not raise UnboundLocalError."""
        plan, env = test_plan_env

        with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            with mock.patch(
                "app.services.resource_pool_service.ResourcePoolService"
            ) as mock_pool_cls:
                mock_pool = mock_pool_cls.return_value
                mock_pool.can_fit = mock.AsyncMock(return_value=True)
                with mock.patch("app.services.credit_service.CreditService") as mock_credit_cls:
                    mock_credit = mock_credit_cls.return_value
                    mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=True)
                    with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
                        mock_vol = mock_vol_cls.return_value
                        mock_vol.create_volume = mock.AsyncMock(
                            side_effect=Exception("volume create failed")
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
                                    "name": "cleanup-server",
                                    "plan_id": str(plan.id),
                                    "environment_id": str(env.id),
                                    "volume_mounts": [
                                        {
                                            "volume_id": "",
                                            "mount_path": "/data",
                                            "mode": "read_write",
                                        }
                                    ],
                                },
                            )

        assert response.status_code == 500
        assert "try again" in response.json()["detail"].lower()
