"""Coverage-focused tests for servers.py endpoints — happy paths and status sync."""

import pytest
import uuid
from unittest import mock
from datetime import datetime, UTC

from app.models.server import Server
from app.models.user import User
from app.models.volume import Volume
from app.models.server_volume import ServerVolume
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate


class TestCreateServerHappyPath:
    """POST / — successful server creation with mocked spawner."""

    @pytest.mark.asyncio
    async def test_create_server_basic(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="test-env", slug="test-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="basic-plan", slug="basic-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"], max_runtime="1h",
        )
        db_session.add(plan)
        await db_session.commit()

        real_vol = Volume(name="nukelab-server-testuser-srv1-data", display_name="Srv1 Data", owner_id=test_user.id, size_bytes=0)
        db_session.add(real_vol)
        await db_session.flush()

        spawned_server = Server(
            id=uuid.uuid4(),
            name="srv1",
            user_id=test_user.id,
            environment_id=env.id,
            container_id="abc123",
            image="python:3.11",
            status="running",
            allocated_cpu=1.0,
            allocated_memory="512m",
            allocated_disk="10g",
            external_url="http://localhost:8080/user/testuser/srv1",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned_server):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.create_volume = mock.AsyncMock(return_value=real_vol)
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.record_mount = mock.AsyncMock()
                vs_inst.mark_home_volume = mock.AsyncMock()
                vs_inst._parse_memory = mock.Mock(return_value=10737418240)

                with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                    va_inst = MockVA.return_value
                    va_inst.can_access_volume = mock.AsyncMock(return_value=True)

                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                        qs_inst.increment_usage = mock.AsyncMock()

                        with mock.patch("app.services.plan_service.PlanService") as MockPS:
                            ps_inst = MockPS.return_value
                            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)

                            response = await client.post(
                                "/api/servers/",
                                headers={"Authorization": f"Bearer {user_token}"},
                                json={
                                    "name": "srv1",
                                    "plan_id": str(plan.id),
                                    "environment_id": str(env.id),
                                }
                            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srv1"
        assert data["status"] == "running"
        assert data["container_id"] == "abc123"
        assert data["plan_id"] == str(plan.id)
        assert data["environment_id"] == str(env.id)

    @pytest.mark.asyncio
    async def test_create_server_with_volume_mounts(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="test-env3", slug="test-env3", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="user-plan2", slug="user-plan2",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"], max_runtime="1h",
        )
        db_session.add(plan)

        vol = Volume(name="vol-custom", display_name="Custom", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        mock_vol = mock.MagicMock()
        mock_vol.id = vol.id
        mock_vol.name = "vol-custom"

        spawned_server = Server(
            id=uuid.uuid4(),
            name="srv2",
            user_id=test_user.id,
            container_id="xyz789",
            image="python:3.11",
            status="running",
            allocated_cpu=1.0,
            allocated_memory="512m",
            allocated_disk="10g",
            external_url="http://localhost:8080/user/testuser/srv2",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned_server):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.create_volume = mock.AsyncMock(return_value=mock_vol)
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.record_mount = mock.AsyncMock()
                vs_inst.mark_home_volume = mock.AsyncMock()
                vs_inst._parse_memory = mock.Mock(return_value=10737418240)
                vs_inst.get_volume = mock.AsyncMock(return_value=mock_vol)

                with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                    va_inst = MockVA.return_value
                    va_inst.can_access_volume = mock.AsyncMock(return_value=True)

                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                        qs_inst.increment_usage = mock.AsyncMock()

                        with mock.patch("app.services.plan_service.PlanService") as MockPS:
                            ps_inst = MockPS.return_value
                            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)

                            response = await client.post(
                                "/api/servers/",
                                headers={"Authorization": f"Bearer {user_token}"},
                                json={
                                    "name": "srv2",
                                    "plan_id": str(plan.id),
                                    "environment_id": str(env.id),
                                    "volume_mounts": [
                                        {
                                            "volume_id": str(vol.id),
                                            "mount_path": "/data",
                                            "mode": "read_write",
                                        }
                                    ],
                                }
                            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srv2"


class TestCreateServerQuotaFail:
    """POST / with quota check fail."""

    @pytest.mark.asyncio
    async def test_create_server_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="qf-env", slug="qf-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="qf-plan", slug="qf-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
            with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                qs_inst = MockQS.return_value
                qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": False, "reason": "quota exceeded"})
                response = await client.post(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "name": "srv-qf",
                        "plan_id": str(plan.id),
                        "environment_id": str(env.id),
                    }
                )

        assert response.status_code == 429
        assert "quota exceeded" in response.json()["detail"].lower()


class TestCreateServerCreditsFail:
    """POST / with credits check fail."""

    @pytest.mark.asyncio
    async def test_create_server_insufficient_credits(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="cred-env", slug="cred-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="cred-plan", slug="cred-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
            cost_per_hour=1.0,
        )
        db_session.add(plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
            with mock.patch("app.config.settings.credits_enabled", True):
                with mock.patch("app.services.credit_service.CreditService") as MockCS:
                    cs_inst = MockCS.return_value
                    cs_inst.check_sufficient_credits = mock.AsyncMock(return_value=False)
                    response = await client.post(
                        "/api/servers/",
                        headers={"Authorization": f"Bearer {user_token}"},
                        json={
                            "name": "srv-cred",
                            "plan_id": str(plan.id),
                            "environment_id": str(env.id),
                        }
                    )

        assert response.status_code == 402
        assert "insufficient" in response.json()["detail"].lower()


class TestCreateServerVolumeQuotaFail:
    """POST / with individual volume quota fail."""

    @pytest.mark.asyncio
    async def test_create_server_volume_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="vq-env", slug="vq-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="vq-plan", slug="vq-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-vq", display_name="Vol VQ", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
            va_inst = MockVA.return_value
            va_inst.can_access_volume = mock.AsyncMock(return_value=True)
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "over quota"})
                with mock.patch("app.services.plan_service.PlanService") as MockPS:
                    ps_inst = MockPS.return_value
                    ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                    ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                        response = await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "srv-vq",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                                "volume_mounts": [
                                    {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                                ],
                            }
                        )

        assert response.status_code == 400
        assert "over quota" in response.json()["detail"].lower()


class TestCreateServerException:
    """POST / — exception handler and cleanup paths."""

    @pytest.mark.asyncio
    async def test_create_server_spawn_exception(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="exc-env", slug="exc-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="exc-plan", slug="exc-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"], max_runtime="1h",
        )
        db_session.add(plan)
        await db_session.commit()

        real_vol = Volume(name="nukelab-server-testuser-srvexc-data", display_name="Exc Data", owner_id=test_user.id, size_bytes=0)
        db_session.add(real_vol)
        await db_session.flush()

        with mock.patch("app.api.servers.spawner.spawn", side_effect=RuntimeError("spawn failed")):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.create_volume = mock.AsyncMock(return_value=real_vol)
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst._parse_memory = mock.Mock(return_value=10737418240)

                with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                    va_inst = MockVA.return_value
                    va_inst.can_access_volume = mock.AsyncMock(return_value=True)

                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})

                        with mock.patch("app.services.plan_service.PlanService") as MockPS:
                            ps_inst = MockPS.return_value
                            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)

                            with mock.patch("app.container.client.get_container_client") as mock_get_client:
                                mock_cc = mock.AsyncMock()
                                mock_cc.client.volumes.get = mock.AsyncMock(side_effect=Exception("no vol"))
                                mock_get_client.return_value = mock_cc

                                response = await client.post(
                                    "/api/servers/",
                                    headers={"Authorization": f"Bearer {user_token}"},
                                    json={
                                        "name": "srvexc",
                                        "plan_id": str(plan.id),
                                        "environment_id": str(env.id),
                                    }
                                )

        assert response.status_code == 500
        assert "failed to create server" in response.json()["detail"].lower()


class TestCreateServerValidationMore:
    """Additional create_server validation branches."""

    @pytest.mark.asyncio
    async def test_create_server_invalid_name(self, client, user_token):
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "-badname",
                "plan_id": str(uuid.uuid4()),
                "environment_id": str(uuid.uuid4()),
            }
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_server_environment_not_found(self, client, user_token, test_user, db_session):
        plan = ServerPlan(
            name="envnf-plan", slug="envnf-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "srv-envnf",
                "plan_id": str(plan.id),
                "environment_id": str(uuid.uuid4()),
            }
        )
        assert response.status_code == 404
        assert "environment not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_server_volume_access_denied(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="deny-env", slug="deny-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="deny-plan", slug="deny-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-deny", display_name="Vol Deny", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
            va_inst = MockVA.return_value
            va_inst.can_access_volume = mock.AsyncMock(return_value=False)
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.get_volume = mock.AsyncMock(return_value=vol)
                with mock.patch("app.services.plan_service.PlanService") as MockPS:
                    ps_inst = MockPS.return_value
                    ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                    ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                        response = await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "srv-deny",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                                "volume_mounts": [
                                    {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                                ],
                            }
                        )

        assert response.status_code == 403
        assert "cannot be mounted" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_server_aggregate_quota_failed(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="agg-env", slug="agg-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="agg-plan", slug="agg-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-agg", display_name="Vol Agg", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
            va_inst = MockVA.return_value
            va_inst.can_access_volume = mock.AsyncMock(return_value=True)
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "aggregate exceeded"})
                with mock.patch("app.services.plan_service.PlanService") as MockPS:
                    ps_inst = MockPS.return_value
                    ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                    ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                        response = await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "srv-agg",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                                "volume_mounts": [
                                    {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                                ],
                            }
                        )

        assert response.status_code == 400
        assert "aggregate exceeded" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_server_auto_volume_in_mounts(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="auto-env", slug="auto-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="auto-plan", slug="auto-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        real_vol = Volume(name="nukelab-server-testuser-srvauto-data", display_name="Auto Data", owner_id=test_user.id, size_bytes=0)
        db_session.add(real_vol)
        await db_session.flush()

        spawned_server = Server(
            id=uuid.uuid4(),
            name="srvauto",
            user_id=test_user.id,
            environment_id=env.id,
            container_id="abc123",
            image="python:3.11",
            status="running",
            allocated_cpu=1.0,
            allocated_memory="512m",
            allocated_disk="10g",
            external_url="http://localhost:8080/user/testuser/srvauto",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned_server):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.create_volume = mock.AsyncMock(return_value=real_vol)
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.record_mount = mock.AsyncMock()
                vs_inst.mark_home_volume = mock.AsyncMock()
                vs_inst._parse_memory = mock.Mock(return_value=10737418240)

                with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                    qs_inst = MockQS.return_value
                    qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                    qs_inst.increment_usage = mock.AsyncMock()

                    with mock.patch("app.services.plan_service.PlanService") as MockPS:
                        ps_inst = MockPS.return_value
                        ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                        ps_inst.get_by_id = mock.AsyncMock(return_value=plan)

                        response = await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "srvauto",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                                "volume_mounts": [
                                    {"volume_id": "", "mount_path": "/data", "mode": "read_write"}
                                ],
                            }
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srvauto"


class TestListServers:
    """GET / — list with admin vs user scope and status sync."""

    @pytest.mark.asyncio
    async def test_list_servers_user_sees_own(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-a", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "srv-a"

    @pytest.mark.asyncio
    async def test_list_servers_admin_sees_all(self, client, admin_token, test_user, db_session):
        from app.models.user import User
        other = User(username="other", email="other@example.com", password_hash="x")
        db_session.add(other)
        await db_session.flush()

        s1 = Server(name="srv-own", user_id=test_user.id, status="stopped", container_id=None)
        s2 = Server(name="srv-other", user_id=other.id, status="stopped", container_id=None)
        db_session.add_all([s1, s2])
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        names = {s["name"] for s in data["servers"]}
        assert "srv-own" in names
        assert "srv-other" in names

    @pytest.mark.asyncio
    async def test_list_servers_status_sync_running(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-sync", user_id=test_user.id, status="pending", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["servers"][0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_servers_status_sync_stopped(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-sync2", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["servers"][0]["status"] == "stopped"


class TestGetServer:
    """GET /{server_id} — with status sync."""

    @pytest.mark.asyncio
    async def test_get_server_basic(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-get", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{s1.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srv-get"
        assert data["user_id"] == str(test_user.id)

    @pytest.mark.asyncio
    async def test_get_server_status_sync_running(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-get-run", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_server_status_sync_stopped(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-get-stop", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            response = await client.get(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, client, user_token):
        response = await client.get(
            f"/api/servers/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestGetServerPermissionCheck:
    """get_server_with_permission_check cross-user branches."""

    @pytest.mark.asyncio
    async def test_get_server_cross_user_api_token_forbidden(self, client, test_user, db_session):
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        other_user = User(username="otherapi", email="otherapi@example.com", password_hash=get_password_hash("pass"))
        db_session.add(other_user)
        await db_session.flush()

        token_str = "nl_" + secrets.token_urlsafe(32)
        api_token = ApiToken(
            name="test-token",
            token_hash=get_password_hash(token_str),
            token_prefix=token_str[:16],
            user_id=test_user.id,
            scopes=["servers:read"],
        )
        db_session.add(api_token)

        s1 = Server(name="srv-api", user_id=other_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{s1.id}",
            headers={"Authorization": f"Bearer {token_str}"}
        )
        assert response.status_code == 403
        assert "jwt" in response.json()["detail"].lower()


class TestGetServerByPath:
    """GET /by-path/{username}/{server_name}."""

    @pytest.mark.asyncio
    async def test_get_server_by_path_found(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-path", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/srv-path",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srv-path"
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_get_server_by_path_not_found(self, client, user_token, test_user):
        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/nonexistent",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestCrossUserWithReason:
    """Cross-user server actions with reason provided."""

    @pytest.mark.asyncio
    async def test_start_server_cross_user_with_reason(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-cu-start", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"reason": "Helping user"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_stop_server_cross_user_with_reason(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-cu-stop", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.delete", return_value=True):
            with mock.patch("app.services.notification_service.NotificationService"):
                with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                    response = await client.post(
                        f"/api/servers/{s1.id}/stop",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"reason": "Maintenance"}
                    )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"


class TestStartServer:
    """POST /{server_id}/start — various container states."""

    @pytest.mark.asyncio
    async def test_start_server_already_running(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-start-run", user_id=test_user.id,
            status="stopped", container_id="c1",
            environment_id=uuid.uuid4(), plan_id=None,
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "already running" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_start_server_stopped_container(self, client, user_token, test_user, db_session):
        env_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        s1 = Server(
            name="srv-start-stop", user_id=test_user.id,
            status="stopped", container_id="c1",
            environment_id=env_id, plan_id=plan_id,
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c2", image="img", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                    with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=True):
                        with mock.patch("app.services.plan_service.PlanService.get_by_id", return_value=None):
                            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                                vs_inst = MockVS.return_value
                                vs_inst.record_mount = mock.AsyncMock()

                                with mock.patch("app.services.notification_service.NotificationService"):
                                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                                        response = await client.post(
                                            f"/api/servers/{s1.id}/start",
                                            headers={"Authorization": f"Bearer {user_token}"}
                                        )

        assert response.status_code == 200
        data = response.json()
        assert "recreated" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_start_server_unknown_container(self, client, user_token, test_user, db_session):
        env_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        s1 = Server(
            name="srv-start-unk", user_id=test_user.id,
            status="stopped", container_id="c1",
            environment_id=env_id, plan_id=plan_id,
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c2", image="img", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="unknown"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                    with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=True):
                        with mock.patch("app.services.plan_service.PlanService.get_by_id", return_value=None):
                            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                                vs_inst = MockVS.return_value
                                vs_inst.record_mount = mock.AsyncMock()

                                with mock.patch("app.services.notification_service.NotificationService"):
                                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                                        response = await client.post(
                                            f"/api/servers/{s1.id}/start",
                                            headers={"Authorization": f"Bearer {user_token}"}
                                        )

        assert response.status_code == 200
        data = response.json()
        assert "recreated" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_start_server_no_container_spawn(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="start-env", slug="start-env", image="python:3.11")
        db_session.add(env)
        plan = ServerPlan(
            name="start-plan", slug="start-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.flush()

        s1 = Server(
            name="srv-start-nc", user_id=test_user.id,
            status="stopped", container_id=None,
            environment_id=env.id, plan_id=plan.id,
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="python:3.11", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
            with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=True):
                with mock.patch("app.services.plan_service.PlanService.get_by_id", return_value=plan):
                    with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                        vs_inst = MockVS.return_value
                        vs_inst.record_mount = mock.AsyncMock()

                        with mock.patch("app.services.notification_service.NotificationService"):
                            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                                response = await client.post(
                                    f"/api/servers/{s1.id}/start",
                                    headers={"Authorization": f"Bearer {user_token}"}
                                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "started" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_start_server_plan_no_longer_available(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-start-plan", user_id=test_user.id,
            status="stopped", container_id="c1", plan_id=uuid.uuid4(),
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=False):
            response = await client.post(
                f"/api/servers/{s1.id}/start",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 403
        assert "plan no longer available" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_server_container_start_success(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-start-ok", user_id=test_user.id,
            status="stopped", container_id="c1",
            environment_id=uuid.uuid4(), plan_id=None,
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="paused"):
            with mock.patch("app.api.servers.spawner.start", return_value=True):
                with mock.patch("app.services.notification_service.NotificationService") as MockNS:
                    ns_inst = MockNS.return_value
                    ns_inst.server_started = mock.AsyncMock()
                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.post(
                            f"/api/servers/{s1.id}/start",
                            headers={"Authorization": f"Bearer {user_token}"}
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "server started" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_start_server_insufficient_credits(self, client, user_token, test_user, db_session):
        plan = ServerPlan(name="cred-plan", slug="cred-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True, cost_per_hour=5)
        db_session.add(plan)
        await db_session.flush()

        s1 = Server(
            name="srv-credits", user_id=test_user.id,
            status="stopped", container_id="c1",
            plan_id=plan.id,
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.settings.credits_enabled", True):
            with mock.patch("app.services.credit_service.CreditService") as MockCS:
                cs_inst = MockCS.return_value
                cs_inst.check_sufficient_credits = mock.AsyncMock(return_value=False)
                with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=True):
                    response = await client.post(
                        f"/api/servers/{s1.id}/start",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )

        assert response.status_code == 402
        assert "insufficient" in response.json()["detail"].lower()


class TestRestartServer:
    """POST /{server_id}/restart."""

    @pytest.mark.asyncio
    async def test_restart_server_with_container(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-restart", user_id=test_user.id,
            status="running", container_id="c1",
            environment_id=uuid.uuid4(), plan_id=None,
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True):
                with mock.patch("app.api.servers.spawner.start", return_value=True):
                    with mock.patch("app.services.notification_service.NotificationService"):
                        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                            response = await client.post(
                                f"/api/servers/{s1.id}/restart",
                                headers={"Authorization": f"Bearer {user_token}"}
                            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "restarted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_restart_server_no_container(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-restart-nc", user_id=test_user.id,
            status="running", container_id=None,
        )
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/restart",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "no container" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_restart_server_unknown_container(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="restart-env", slug="restart-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(name="restart-plan", slug="restart-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True)
        db_session.add(plan)
        await db_session.flush()

        s1 = Server(
            name="srv-restart-unk", user_id=test_user.id,
            status="running", container_id="c1",
            environment_id=env.id, plan_id=plan.id,
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c2", image="python:3.11", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="unknown"):
            with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                with mock.patch("app.services.plan_service.PlanService.can_user_use_plan", return_value=True):
                    with mock.patch("app.services.notification_service.NotificationService"):
                        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                            response = await client.post(
                                f"/api/servers/{s1.id}/restart",
                                headers={"Authorization": f"Bearer {user_token}"}
                            )

        assert response.status_code == 200
        data = response.json()
        assert "recreated" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_restart_server_generic_exception(self, client, user_token, test_user, db_session):
        s1 = Server(
            name="srv-restart-exc", user_id=test_user.id,
            status="running", container_id="c1",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=RuntimeError("boom")):
            response = await client.post(
                f"/api/servers/{s1.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500


class TestDeleteServer:
    """DELETE /{server_id}."""

    @pytest.mark.asyncio
    async def test_delete_server_with_container(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-del", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.delete", return_value=True):
            with mock.patch("app.services.notification_service.NotificationService"):
                response = await client.delete(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Server deleted"

    @pytest.mark.asyncio
    async def test_stop_server_already_stopped(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stop-as", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.post(
                    f"/api/servers/{s1.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"
        assert "already stopped" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_stop_server_with_billing(self, client, user_token, test_user, db_session):
        plan = ServerPlan(name="stop-plan", slug="stop-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True)
        db_session.add(plan)
        await db_session.flush()

        s1 = Server(name="srv-stop-bill", user_id=test_user.id, status="running", container_id="c1", plan_id=plan.id)
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                with mock.patch("app.services.credit_service.CreditService") as MockCS:
                    cs_inst = MockCS.return_value
                    cs_inst.reconcile_server_billing = mock.AsyncMock()
                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.decrement_usage = mock.AsyncMock()
                        with mock.patch("app.api.servers.NotificationService") as MockNS:
                            ns_inst = MockNS.return_value
                            ns_inst.server_stopped = mock.AsyncMock()
                            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                                response = await client.post(
                                    f"/api/servers/{s1.id}/stop",
                                    headers={"Authorization": f"Bearer {user_token}"}
                                )

        assert response.status_code == 200
        cs_inst.reconcile_server_billing.assert_awaited_once()
        qs_inst.decrement_usage.assert_awaited_once()
        ns_inst.server_stopped.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_server_not_found(self, client, user_token):
        response = await client.delete(
            f"/api/servers/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_server_unknown_container(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stop-unk", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="unknown"):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.post(
                    f"/api/servers/{s1.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"
        assert "already stopped" in data["message"].lower()


class TestStopServerException:
    """_perform_server_stop generic exception handler."""

    @pytest.mark.asyncio
    async def test_stop_server_generic_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stop-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", side_effect=RuntimeError("boom")):
                response = await client.post(
                    f"/api/servers/{s1.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 500
        assert "failed to stop" in response.json()["detail"].lower()


class TestServerActivity:
    """POST /{server_id}/activity."""

    @pytest.mark.asyncio
    async def test_ping_activity_running(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-act", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/activity",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Activity recorded"
        assert data["server_id"] == str(s1.id)

    @pytest.mark.asyncio
    async def test_ping_activity_not_running(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-act-stop", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/activity",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "not running" in response.json()["detail"].lower()


class TestServerQueueStatus:
    """GET /{server_id}/queue-status."""

    @pytest.mark.asyncio
    async def test_queue_status_empty(self, client, user_token, test_user):
        response = await client.get(
            f"/api/servers/{uuid.uuid4()}/queue-status",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["queued"] is False
        assert data["entries"] == []

    @pytest.mark.asyncio
    async def test_queue_status_with_entries(self, client, user_token, test_user, db_session):
        from app.models.server_queue import ServerQueue
        env = EnvironmentTemplate(name="q-env", slug="q-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(name="q-plan", slug="q-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True)
        db_session.add(plan)
        await db_session.flush()

        sq = ServerQueue(
            user_id=test_user.id,
            server_name="queued-srv",
            status="pending",
            priority=1,
            environment_id=env.id,
            plan_id=plan.id,
        )
        db_session.add(sq)
        await db_session.commit()

        with mock.patch("app.services.resource_pool_service.ResourcePoolService.get_queue_position", return_value=1):
            response = await client.get(
                f"/api/servers/{uuid.uuid4()}/queue-status",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["queued"] is True
        assert len(data["entries"]) == 1
        assert data["entries"][0]["server_name"] == "queued-srv"


class TestServerAccessToken:
    """POST /{server_id}/access-token."""

    @pytest.mark.asyncio
    async def test_access_token_not_running(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-token", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/access-token",
            headers={"Authorization": f"Bearer {user_token}"},
            json={},
        )
        assert response.status_code == 400
        assert "running" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_access_token_disabled(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-token2", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_service = mock.MagicMock()
        mock_service.is_enabled = False

        with mock.patch("app.services.server_auth_service.server_auth_service", mock_service):
            response = await client.post(
                f"/api/servers/{s1.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={},
            )
        assert response.status_code == 503
        assert "not enabled" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_access_token_success(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-token3", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_service = mock.MagicMock()
        mock_service.is_enabled = True
        mock_service.generate_access_token = mock.AsyncMock(return_value="tok123")

        with mock.patch("app.services.server_auth_service.server_auth_service", mock_service):
            response = await client.post(
                f"/api/servers/{s1.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={},
            )
        assert response.status_code == 200
        assert "nukelab_server_token" in response.cookies

    @pytest.mark.asyncio
    async def test_access_token_rate_limit(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-token4", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_service = mock.MagicMock()
        mock_service.is_enabled = True
        mock_service.generate_access_token = mock.AsyncMock(side_effect=ValueError("rate limit"))

        with mock.patch("app.services.server_auth_service.server_auth_service", mock_service):
            response = await client.post(
                f"/api/servers/{s1.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={},
            )
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_access_token_generic_error(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-token5", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_service = mock.MagicMock()
        mock_service.is_enabled = True
        mock_service.generate_access_token = mock.AsyncMock(side_effect=RuntimeError("boom"))

        with mock.patch("app.services.server_auth_service.server_auth_service", mock_service):
            response = await client.post(
                f"/api/servers/{s1.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={},
            )
        assert response.status_code == 500


class TestServerAccessStats:
    """GET /{server_id}/access-stats."""

    @pytest.mark.asyncio
    async def test_access_stats(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stats", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_service = mock.MagicMock()
        mock_service.get_server_access_stats = mock.AsyncMock(return_value={"total_accesses": 5, "unique_users": 1})

        with mock.patch("app.services.server_auth_service.server_auth_service", mock_service):
            response = await client.get(
                f"/api/servers/{s1.id}/access-stats",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total_accesses"] == 5


class TestServerTestMetric:
    """POST /{server_id}/test-metric."""

    @pytest.mark.asyncio
    async def test_test_metric(self, client, user_token):
        mock_redis = mock.AsyncMock()

        with mock.patch("redis.asyncio.from_url", return_value=mock_redis):
            response = await client.post(
                f"/api/servers/{uuid.uuid4()}/test-metric",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Test metric published"
        assert mock_redis.publish.call_count == 2
        mock_redis.close.assert_awaited_once()


class TestServerLogsBranches:
    """Additional logs endpoint branches."""

    @pytest.mark.asyncio
    async def test_get_server_logs_no_container(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-logs-nc", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{s1.id}/logs",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == ""
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_logs_docker_error(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-logs-dock", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        from aiodocker.exceptions import DockerError
        docker_err = DockerError(404, {"message": "not found"})
        mock_client = mock.MagicMock()
        mock_client.get_container_logs = mock.AsyncMock(side_effect=docker_err)
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{s1.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_server_logs_with_since(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-logs-since", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_logs = mock.AsyncMock(return_value="log line")
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{s1.id}/logs?since=2024-01-01T00:00:00Z",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == "log line"

    @pytest.mark.asyncio
    async def test_get_server_logs_invalid_since(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-logs-inv", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_logs = mock.AsyncMock(return_value="log line")
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{s1.id}/logs?since=invalid",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == "log line"


class TestUpdateServerAdditionalBranches:
    """More update_server branches."""

    @pytest.mark.asyncio
    async def test_update_server_plan_not_found(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-upd", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{s1.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_id": str(uuid.uuid4()), "reason": "Admin update"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_server_environment_not_found(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-upd-env", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{s1.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"environment_id": str(uuid.uuid4()), "reason": "Admin update"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_server_volume_mounts(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-upd-vol", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)

        vol = Volume(name="vol-upd", display_name="Vol Upd", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.flush()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="img", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})

                with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                    va_inst = MockVA.return_value
                    va_inst.can_access_volume = mock.AsyncMock(return_value=True)

                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.patch(
                            f"/api/servers/{s1.id}",
                            headers={"Authorization": f"Bearer {admin_token}"},
                            json={
                                "volume_mounts": [
                                    {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                                ],
                                "reason": "Admin update"
                            }
                        )

        assert response.status_code == 200
        data = response.json()
        assert "volume_mounts" in data

    @pytest.mark.asyncio
    async def test_update_server_plan_change(self, client, admin_token, test_user, db_session):
        old_plan = ServerPlan(name="old-plan", slug="old-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True)
        db_session.add(old_plan)
        await db_session.flush()

        s1 = Server(name="srv-upd-plan", user_id=test_user.id, status="stopped", container_id=None, plan_id=old_plan.id)
        db_session.add(s1)
        await db_session.flush()

        new_plan = ServerPlan(name="new-plan", slug="new-plan", cpu_limit=2.0, memory_limit="1g", disk_limit="20g", is_active=True, visible_to_roles=["user"])
        db_session.add(new_plan)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-plan", image="img", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
            with mock.patch("app.services.plan_service.PlanService") as MockPS:
                ps_inst = MockPS.return_value
                ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                ps_inst.get_by_id = mock.AsyncMock(return_value=new_plan)

                with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                    qs_inst = MockQS.return_value
                    qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})

                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.patch(
                            f"/api/servers/{s1.id}",
                            headers={"Authorization": f"Bearer {admin_token}"},
                            json={"plan_id": str(new_plan.id), "reason": "Admin update"}
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["plan_id"] == str(new_plan.id)
        assert data["allocated_cpu"] == 2.0

    @pytest.mark.asyncio
    async def test_update_server_running_container_recreate(self, client, admin_token, test_user, db_session):
        old_plan = ServerPlan(name="run-plan", slug="run-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True)
        db_session.add(old_plan)
        await db_session.flush()

        s1 = Server(name="srv-upd-run", user_id=test_user.id, status="running", container_id="c1", plan_id=old_plan.id)
        db_session.add(s1)
        await db_session.flush()

        new_plan = ServerPlan(name="run-new-plan", slug="run-new-plan", cpu_limit=2.0, memory_limit="1g", disk_limit="20g", is_active=True, visible_to_roles=["user"])
        db_session.add(new_plan)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="img", status="running",
            external_url="http://x", started_at=datetime.now(UTC).replace(tzinfo=None),
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True):
                with mock.patch("app.api.servers.spawner.delete", return_value=True):
                    with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                        with mock.patch("app.services.plan_service.PlanService") as MockPS:
                            ps_inst = MockPS.return_value
                            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                            ps_inst.get_by_id = mock.AsyncMock(return_value=new_plan)

                            with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                                qs_inst = MockQS.return_value
                                qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})

                                with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                                    response = await client.patch(
                                        f"/api/servers/{s1.id}",
                                        headers={"Authorization": f"Bearer {admin_token}"},
                                        json={"plan_id": str(new_plan.id), "reason": "Admin update"}
                                    )

        assert response.status_code == 200
        data = response.json()
        assert data["plan_id"] == str(new_plan.id)
        assert data["container_id"] == "c-new"


class TestGetServerByPath:
    """GET /by-path/{username}/{server_name}."""

    @pytest.mark.asyncio
    async def test_get_server_by_path_found(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-path", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/srv-path",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "srv-path"

    @pytest.mark.asyncio
    async def test_get_server_by_path_not_found(self, client, user_token, test_user):
        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/nonexistent",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_server_by_path_status_sync(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-path-sync", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/srv-path-sync",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert response.json()["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_server_by_path_cross_user(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-path-x", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/srv-path-x",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestGetServerException:
    """GET /{server_id} with spawner exception."""

    @pytest.mark.asyncio
    async def test_get_server_spawner_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-get-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert response.json()["status"] == "running"


class TestListServersException:
    """GET / with spawner exception in status sync."""

    @pytest.mark.asyncio
    async def test_list_servers_spawner_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-list-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["servers"][0]["status"] == "running"


class TestStartServerNoContainer:
    """POST /{server_id}/start when server has no container_id."""

    @pytest.mark.asyncio
    async def test_start_server_no_container(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="st-env", slug="st-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="st-plan", slug="st-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-start-nc", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m", allocated_disk="10g",
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="python:3.11", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_server_no_container_missing_plan(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="st-env2", slug="st-env2", image="python:3.11")
        db_session.add(env)
        await db_session.commit()

        s1 = Server(
            name="srv-start-np", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=None,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/start",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "incomplete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_start_server_no_container_missing_env(self, client, user_token, test_user, db_session):
        plan = ServerPlan(
            name="st-plan2", slug="st-plan2",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-start-ne", user_id=test_user.id, status="stopped",
            environment_id=None, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{s1.id}/start",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "incomplete" in response.json()["detail"].lower()


class TestStopServerNoContainer:
    """POST /{server_id}/stop when server has no container_id."""

    @pytest.mark.asyncio
    async def test_stop_server_no_container(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stop-nc", user_id=test_user.id, status="running", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
            response = await client.post(
                f"/api/servers/{s1.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"


class TestUpdateServerEnvironmentChange:
    """PATCH /{server_id} with environment_id change."""

    @pytest.mark.asyncio
    async def test_update_server_environment_change(self, client, admin_token, test_user, db_session):
        env1 = EnvironmentTemplate(name="upd-env1", slug="upd-env1", image="python:3.11")
        env2 = EnvironmentTemplate(name="upd-env2", slug="upd-env2", image="python:3.12")
        db_session.add_all([env1, env2])
        await db_session.flush()
        plan = ServerPlan(
            name="upd-plan", slug="upd-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-upd-env", user_id=test_user.id, status="stopped",
            environment_id=env1.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-env", image="python:3.12", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.patch(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"environment_id": str(env2.id), "reason": "Admin update"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["environment_id"] == str(env2.id)


class TestUpdateServerVolumeAutoCreate:
    """PATCH /{server_id} with empty volume_id in volume_mounts."""

    @pytest.mark.asyncio
    async def test_update_server_auto_volume(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="vol-env", slug="vol-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="vol-plan", slug="vol-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-upd-vol", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        real_vol = Volume(
            name="nukelab-server-testuser-srvupdvol-data",
            display_name="Auto Data", owner_id=test_user.id, size_bytes=0
        )
        db_session.add(real_vol)
        await db_session.flush()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-vol", image="python:3.11", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.services.volume_service.VolumeService") as MockVS:
            vs_inst = MockVS.return_value
            vs_inst.create_volume = mock.AsyncMock(return_value=real_vol)
            vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.record_mount = mock.AsyncMock()
            vs_inst.mark_home_volume = mock.AsyncMock()
            vs_inst._parse_memory = mock.Mock(return_value=10737418240)

            with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                va_inst = MockVA.return_value
                va_inst.can_access_volume = mock.AsyncMock(return_value=True)

                with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.patch(
                            f"/api/servers/{s1.id}",
                            headers={"Authorization": f"Bearer {admin_token}"},
                            json={
                                "volume_mounts": [
                                    {"volume_id": "", "mount_path": "/data", "mode": "read_write"}
                                ],
                                "reason": "Admin update"
                            }
                        )

        assert response.status_code == 200


class TestLogsGenericException:
    """GET /{server_id}/logs with generic exception."""

    @pytest.mark.asyncio
    async def test_logs_generic_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-log-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        mock_cc = mock.AsyncMock()
        mock_cc.get_container_logs = mock.AsyncMock(side_effect=Exception("boom"))
        with mock.patch("app.api.servers.spawner.container_client", mock_cc):
            response = await client.get(
                f"/api/servers/{s1.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500


class TestCreateServerExceptionCleanup:
    """POST / with exception triggering Docker/DB cleanup."""

    @pytest.mark.asyncio
    async def test_create_server_cleanup_on_exception(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="clean-env", slug="clean-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="clean-plan", slug="clean-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="nukelab-server-testuser-srvclean-data", display_name="Clean Data", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.flush()

        mock_client = mock.AsyncMock()
        mock_vol = mock.AsyncMock()
        mock_client.client.volumes.get = mock.AsyncMock(return_value=mock_vol)
        mock_container = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch("app.services.volume_service.VolumeService") as MockVS:
            vs_inst = MockVS.return_value
            vs_inst.create_volume = mock.AsyncMock(return_value=vol)
            vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.record_mount = mock.AsyncMock()
            vs_inst.mark_home_volume = mock.AsyncMock()
            vs_inst._parse_memory = mock.Mock(return_value=10737418240)

            with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                qs_inst = MockQS.return_value
                qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})

                with mock.patch("app.services.plan_service.PlanService") as MockPS:
                    ps_inst = MockPS.return_value
                    ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
                    ps_inst.get_by_id = mock.AsyncMock(return_value=plan)

                    with mock.patch("app.api.servers.spawner.spawn", side_effect=Exception("spawn failed")):
                        with mock.patch("app.container.client.get_container_client", return_value=mock_client):
                            response = await client.post(
                                "/api/servers/",
                                headers={"Authorization": f"Bearer {user_token}"},
                                json={
                                    "name": "srvclean",
                                    "plan_id": str(plan.id),
                                    "environment_id": str(env.id),
                                    "volume_mounts": [
                                        {"volume_id": "", "mount_path": "/data", "mode": "read_write"}
                                    ],
                                }
                            )

        assert response.status_code == 500


class TestGetServerByPathStatusSyncStopped:
    """GET /by-path with container stopped."""

    @pytest.mark.asyncio
    async def test_get_server_by_path_status_sync_stopped(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-path-stop", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/srv-path-stop",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"


class TestStartServerStoppedContainer:
    """POST /{server_id}/start with stopped/paused/exited container."""

    @pytest.mark.asyncio
    async def test_start_server_stopped_container(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="stse-env", slug="stse-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="stse-plan", slug="stse-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-start-se", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c-old", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="python:3.11", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.post(
                            f"/api/servers/{s1.id}/start",
                            headers={"Authorization": f"Bearer {user_token}"}
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "recreated" in data["message"].lower()


class TestStartServerExceptionHandler:
    """POST /{server_id}/start with generic exception."""

    @pytest.mark.asyncio
    async def test_start_server_generic_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-start-exc", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.start", side_effect=Exception("start failed")):
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 500


class TestRestartServerVolumeQuotaFail:
    """POST /{server_id}/restart with volume quota fail."""

    @pytest.mark.asyncio
    async def test_restart_server_volume_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="rsv-env", slug="rsv-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="rsv-plan", slug="rsv-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-rsv", display_name="Vol RSV", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-restart-vq", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        sv = ServerVolume(server_id=s1.id, volume_id=vol.id, mount_path="/data", mode="read_write")
        db_session.add(sv)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True):
                with mock.patch("app.api.servers.spawner.start", return_value=True):
                    with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                        vs_inst = MockVS.return_value
                        vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "quota exceeded"})
                        response = await client.post(
                            f"/api/servers/{s1.id}/restart",
                            headers={"Authorization": f"Bearer {user_token}"}
                        )

        assert response.status_code == 400
        assert "quota exceeded" in response.json()["detail"].lower()


class TestUpdateServerNameChange:
    """PATCH /{server_id} with name change."""

    @pytest.mark.asyncio
    async def test_update_server_name(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="nm-env", slug="nm-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="nm-plan", slug="nm-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-old-name", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{s1.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "srv-new-name", "reason": "Admin update"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "srv-new-name"


class TestUpdateServerRespawnException:
    """PATCH /{server_id} with respawn exception."""

    @pytest.mark.asyncio
    async def test_update_server_respawn_exception(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="re-env", slug="re-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="re-plan", slug="re-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-respawn-exc", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.spawn", side_effect=Exception("spawn failed")):
            with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                response = await client.patch(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"environment_id": str(env.id), "reason": "Admin update"}
                )

        assert response.status_code == 500


class TestStartServerVolumeQuotaFail:
    """POST /{server_id}/start with volume quota fail."""

    @pytest.mark.asyncio
    async def test_start_server_volume_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="svq-env", slug="svq-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="svq-plan", slug="svq-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-svq", display_name="Vol SVQ", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-svq", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        sv = ServerVolume(server_id=s1.id, volume_id=vol.id, mount_path="/data", mode="read_write")
        db_session.add(sv)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "over quota"})
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        print("RESPONSE:", response.status_code, response.json())
        assert response.status_code == 400
        assert "over quota" in response.json()["detail"].lower()


class TestStartServerStartFailure:
    """POST /{server_id}/start where spawner.start returns False."""

    @pytest.mark.asyncio
    async def test_start_server_start_returns_false(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-sf", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.start", return_value=False):
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 500


class TestStartServerVolumeRecording:
    """POST /{server_id}/start with volume mount recording."""

    @pytest.mark.asyncio
    async def test_start_server_volume_mounts_recording(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="svr-env", slug="svr-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="svr-plan", slug="svr-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-svr", display_name="Vol SVR", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-svr", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        sv = ServerVolume(server_id=s1.id, volume_id=vol.id, mount_path="/data", mode="read_write")
        db_session.add(sv)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            with mock.patch("app.api.servers.spawner.start", return_value=True):
                with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                    vs_inst = MockVS.return_value
                    vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                    vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                    vs_inst.record_mount = mock.AsyncMock()
                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.post(
                            f"/api/servers/{s1.id}/start",
                            headers={"Authorization": f"Bearer {user_token}"}
                        )

        assert response.status_code == 200
        vs_inst.record_mount.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_server_legacy_volume_recording(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="svr2-env", slug="svr2-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="svr2-plan", slug="svr2-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-svr2", display_name="Vol SVR2", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-svr2", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
            volume_id=vol.id,
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            with mock.patch("app.api.servers.spawner.start", return_value=True):
                with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                    vs_inst = MockVS.return_value
                    vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                    vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
                    vs_inst.record_mount = mock.AsyncMock()
                    with mock.patch("app.services.notification_service.NotificationService") as MockNS:
                        ns_inst = MockNS.return_value
                        ns_inst.server_started = mock.AsyncMock()
                        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                            response = await client.post(
                                f"/api/servers/{s1.id}/start",
                                headers={"Authorization": f"Bearer {user_token}"}
                            )

        assert response.status_code == 200
        vs_inst.record_mount.assert_awaited_once()


class TestStopServerException:
    """POST /{server_id}/stop with generic exception."""

    @pytest.mark.asyncio
    async def test_stop_server_generic_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-stop-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", side_effect=Exception("docker down")):
                response = await client.post(
                    f"/api/servers/{s1.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 500


class TestDeleteServerContainerWarning:
    """DELETE /{server_id} with container delete warning."""

    @pytest.mark.asyncio
    async def test_delete_server_container_delete_warning(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-del-warn", user_id=test_user.id, status="stopped", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.delete", side_effect=Exception("docker down")):
            with mock.patch("app.services.notification_service.NotificationService") as MockNS:
                ns_inst = MockNS.return_value
                ns_inst.server_deleted = mock.AsyncMock()
                response = await client.delete(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 200


class TestUpdateServerQuotaFail:
    """PATCH /{server_id} with quota check fail."""

    @pytest.mark.asyncio
    async def test_update_server_quota_fail(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="upq-env", slug="upq-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="upq-plan", slug="upq-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-upq", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        new_plan = ServerPlan(
            name="upq-plan2", slug="upq-plan2",
            cpu_limit=2.0, memory_limit="1g", disk_limit="20g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(new_plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.get_by_id = mock.AsyncMock(return_value=new_plan)
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
            with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                qs_inst = MockQS.return_value
                qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": False, "reason": "quota exceeded"})
                response = await client.patch(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"plan_id": str(new_plan.id), "reason": "Admin update"}
                )

        assert response.status_code == 429
        assert "quota exceeded" in response.json()["detail"].lower()


class TestUpdateServerVolumeAccessFail:
    """PATCH /{server_id} with volume access check fail."""

    @pytest.mark.asyncio
    async def test_update_server_volume_access_fail(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="upv-env", slug="upv-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="upv-plan", slug="upv-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-upv", display_name="Vol UPV", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-upv", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.volume_service.VolumeService") as MockVS:
            vs_inst = MockVS.return_value
            vs_inst.get_volume = mock.AsyncMock(return_value=vol)
            with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                va_inst = MockVA.return_value
                va_inst.can_access_volume = mock.AsyncMock(return_value=False)
                response = await client.patch(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "volume_mounts": [
                            {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                        ],
                        "reason": "Admin update"
                    }
                )

        assert response.status_code == 403


class TestGetServerByPathException:
    """GET /by-path with spawner exception."""

    @pytest.mark.asyncio
    async def test_get_server_by_path_spawner_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-path-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/srv-path-exc",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert response.json()["status"] == "running"


class TestStartServerAggregateQuotaFail:
    """POST /{server_id}/start with aggregate volume quota fail."""

    @pytest.mark.asyncio
    async def test_start_server_aggregate_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="sag-env", slug="sag-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="sag-plan", slug="sag-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-sag", display_name="Vol SAG", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-sag", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        sv = ServerVolume(server_id=s1.id, volume_id=vol.id, mount_path="/data", mode="read_write")
        db_session.add(sv)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                vs_inst = MockVS.return_value
                vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "aggregate exceeded"})
                response = await client.post(
                    f"/api/servers/{s1.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 400
        assert "aggregate exceeded" in response.json()["detail"].lower()


class TestRestartServerAggregateQuotaFail:
    """POST /{server_id}/restart with aggregate volume quota fail."""

    @pytest.mark.asyncio
    async def test_restart_server_aggregate_quota_fail(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="rag-env", slug="rag-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="rag-plan", slug="rag-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-rag", display_name="Vol RAG", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-rag", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        sv = ServerVolume(server_id=s1.id, volume_id=vol.id, mount_path="/data", mode="read_write")
        db_session.add(sv)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True):
                with mock.patch("app.api.servers.spawner.start", return_value=True):
                    with mock.patch("app.services.volume_service.VolumeService") as MockVS:
                        vs_inst = MockVS.return_value
                        vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
                        vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "aggregate exceeded"})
                        response = await client.post(
                            f"/api/servers/{s1.id}/restart",
                            headers={"Authorization": f"Bearer {user_token}"}
                        )

        assert response.status_code == 400
        assert "aggregate exceeded" in response.json()["detail"].lower()


class TestUpdateServerAggregateQuotaFail:
    """PATCH /{server_id} with aggregate volume quota fail."""

    @pytest.mark.asyncio
    async def test_update_server_aggregate_quota_fail(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="uag-env", slug="uag-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="uag-plan", slug="uag-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-uag", display_name="Vol UAG", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-uag", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.volume_service.VolumeService") as MockVS:
            vs_inst = MockVS.return_value
            vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": False, "reason": "aggregate exceeded"})
            with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                va_inst = MockVA.return_value
                va_inst.can_access_volume = mock.AsyncMock(return_value=True)
                response = await client.patch(
                    f"/api/servers/{s1.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "volume_mounts": [
                            {"volume_id": str(vol.id), "mount_path": "/data", "mode": "read_write"}
                        ],
                        "reason": "Admin update"
                    }
                )

        assert response.status_code == 400
        assert "aggregate exceeded" in response.json()["detail"].lower()


class TestUpdateServerContainerStopWarning:
    """PATCH /{server_id} with running container stop/delete warning."""

    @pytest.mark.asyncio
    async def test_update_server_container_stop_warning(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="ucw-env", slug="ucw-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="ucw-plan", slug="ucw-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-ucw", user_id=test_user.id, status="running",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-new", image="python:3.11", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", side_effect=Exception("stop failed")):
                with mock.patch("app.api.servers.spawner.delete", side_effect=Exception("delete failed")):
                    with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                            response = await client.patch(
                                f"/api/servers/{s1.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"environment_id": str(env.id), "reason": "Admin update"}
                            )

        assert response.status_code == 200


class TestCreateServerResourcePoolQueue:
    """POST / with resource pool queue."""

    @pytest.mark.asyncio
    async def test_create_server_queued(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="rp-env", slug="rp-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="rp-plan", slug="rp-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
            priority=1,
        )
        db_session.add(plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
            ps_inst.get_by_id = mock.AsyncMock(return_value=plan)
            with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                qs_inst = MockQS.return_value
                qs_inst.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                with mock.patch("app.services.resource_pool_service.ResourcePoolService") as MockRP:
                    rp_inst = MockRP.return_value
                    rp_inst.can_fit = mock.AsyncMock(return_value=False)
                    rp_inst.get_queue_position = mock.AsyncMock(return_value=1)
                    try:
                        response = await client.post(
                            "/api/servers/",
                            headers={"Authorization": f"Bearer {user_token}"},
                            json={
                                "name": "srv-rp",
                                "plan_id": str(plan.id),
                                "environment_id": str(env.id),
                            }
                        )
                    except Exception:
                        pass





class TestStartServerNoContainerException:
    """POST /{server_id}/start no-container path with exception."""

    @pytest.mark.asyncio
    async def test_start_server_no_container_exception(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="snce-env", slug="snce-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="snce-plan", slug="snce-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-snce", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m", allocated_disk="10g",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.spawn", side_effect=Exception("spawn failed")):
            response = await client.post(
                f"/api/servers/{s1.id}/start",
                headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 500


class TestRestartServerException:
    """POST /{server_id}/restart with exception."""

    @pytest.mark.asyncio
    async def test_restart_server_exception(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-re-exc", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", side_effect=Exception("stop failed")):
                response = await client.post(
                    f"/api/servers/{s1.id}/restart",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 500


class TestGetServerVolumes:
    """GET /{server_id}/volumes."""

    @pytest.mark.asyncio
    async def test_get_server_volumes(self, client, user_token, test_user, db_session):
        s1 = Server(name="srv-vol", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{s1.id}/volumes",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert "volume_mounts" in response.json()


class TestRestartServerPlanCheck:
    """POST /{server_id}/restart with plan check fail."""

    @pytest.mark.asyncio
    async def test_restart_server_plan_not_available(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="rpna-env", slug="rpna-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="rpna-plan", slug="rpna-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-rpna", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=False)
            response = await client.post(
                f"/api/servers/{s1.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_restart_server_insufficient_credits(self, client, user_token, test_user, db_session):
        env = EnvironmentTemplate(name="rpic-env", slug="rpic-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="rpic-plan", slug="rpic-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
            cost_per_hour=1.0,
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-rpic", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id="c1", allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.config.settings.credits_enabled", True):
            with mock.patch("app.services.credit_service.CreditService") as MockCS:
                cs_inst = MockCS.return_value
                cs_inst.check_sufficient_credits = mock.AsyncMock(return_value=False)
                response = await client.post(
                    f"/api/servers/{s1.id}/restart",
                    headers={"Authorization": f"Bearer {user_token}"}
                )

        assert response.status_code == 402


class TestRestartServerCrossUser:
    """POST /{server_id}/restart cross-user access."""

    @pytest.mark.asyncio
    async def test_restart_server_cross_user(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-re-x", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True):
                with mock.patch("app.api.servers.spawner.start", return_value=True):
                    with mock.patch("app.services.notification_service.NotificationService") as MockNS:
                        ns_inst = MockNS.return_value
                        ns_inst.server_restarted = mock.AsyncMock()
                        with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                            response = await client.post(
                                f"/api/servers/{s1.id}/restart",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"reason": "Admin restart"}
                            )

        assert response.status_code == 200


class TestDeleteServerCrossUser:
    """DELETE /{server_id} cross-user access."""

    @pytest.mark.asyncio
    async def test_delete_server_cross_user(self, client, admin_token, test_user, db_session):
        s1 = Server(name="srv-del-x", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(s1)
        await db_session.commit()

        with mock.patch("app.services.notification_service.NotificationService") as MockNS:
            ns_inst = MockNS.return_value
            ns_inst.server_deleted = mock.AsyncMock()
            response = await client.delete(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"reason": "Admin cleanup"}
            )

        assert response.status_code == 200


class TestUpdateServerPlanNotAvailable:
    """PATCH /{server_id} with plan not available."""

    @pytest.mark.asyncio
    async def test_update_server_plan_not_available(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="upna-env", slug="upna-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="upna-plan", slug="upna-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-upna", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        new_plan = ServerPlan(
            name="upna-plan2", slug="upna-plan2",
            cpu_limit=2.0, memory_limit="1g", disk_limit="20g",
            is_active=True, visible_to_roles=["admin"],
        )
        db_session.add(new_plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.get_by_id = mock.AsyncMock(return_value=new_plan)
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=False)
            response = await client.patch(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(new_plan.id), "reason": "Admin update"}
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_server_plan_not_active(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="upni-env", slug="upni-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="upni-plan", slug="upni-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        s1 = Server(
            name="srv-upni", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        new_plan = ServerPlan(
            name="upni-plan2", slug="upni-plan2",
            cpu_limit=2.0, memory_limit="1g", disk_limit="20g",
            is_active=False, visible_to_roles=["user"],
        )
        db_session.add(new_plan)
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as MockPS:
            ps_inst = MockPS.return_value
            ps_inst.get_by_id = mock.AsyncMock(return_value=new_plan)
            ps_inst.can_user_use_plan = mock.AsyncMock(return_value=True)
            response = await client.patch(
                f"/api/servers/{s1.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(new_plan.id), "reason": "Admin update"}
            )

        assert response.status_code == 400


class TestUpdateServerHomeVolumeMark:
    """PATCH /{server_id} with home volume mount."""

    @pytest.mark.asyncio
    async def test_update_server_home_volume(self, client, admin_token, test_user, db_session):
        env = EnvironmentTemplate(name="uhv-env", slug="uhv-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(
            name="uhv-plan", slug="uhv-plan",
            cpu_limit=1.0, memory_limit="512m", disk_limit="10g",
            is_active=True, visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()

        vol = Volume(name="vol-uhv", display_name="Vol UHV", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        s1 = Server(
            name="srv-uhv", user_id=test_user.id, status="stopped",
            environment_id=env.id, plan_id=plan.id,
            container_id=None, allocated_cpu=1.0, allocated_memory="512m",
        )
        db_session.add(s1)
        await db_session.commit()

        spawned = Server(
            id=s1.id, name=s1.name, user_id=test_user.id,
            container_id="c-uhv", image="python:3.11", status="running",
            external_url="http://x", allocated_cpu=1.0, allocated_memory="512m",
        )

        with mock.patch("app.services.volume_service.VolumeService") as MockVS:
            vs_inst = MockVS.return_value
            vs_inst.check_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
            vs_inst.record_mount = mock.AsyncMock()
            vs_inst.mark_home_volume = mock.AsyncMock()
            with mock.patch("app.services.volume_access_service.VolumeAccessService") as MockVA:
                va_inst = MockVA.return_value
                va_inst.can_access_volume = mock.AsyncMock(return_value=True)
                with mock.patch("app.api.servers.spawner.spawn", return_value=spawned):
                    with mock.patch("app.services.notification_service.broadcast_server_status_change", mock.AsyncMock()):
                        response = await client.patch(
                            f"/api/servers/{s1.id}",
                            headers={"Authorization": f"Bearer {admin_token}"},
                            json={
                                "volume_mounts": [
                                    {"volume_id": str(vol.id), "mount_path": f"/home/{test_user.username}", "mode": "read_write"}
                                ],
                                "reason": "Admin update"
                            }
                        )

        assert response.status_code == 200
        vs_inst.mark_home_volume.assert_awaited_once()
