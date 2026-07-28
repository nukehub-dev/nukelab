# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for GET /api/servers/{id}/tasks (read-only container process list)."""

from unittest import mock

import pytest

from app.container.driver import ContainerDriverError
from app.models.server import Server

TOP_PAYLOAD = {
    "Titles": [
        "USER",
        "PID",
        "%CPU",
        "%MEM",
        "VSZ",
        "RSS",
        "TTY",
        "STAT",
        "START",
        "TIME",
        "COMMAND",
    ],
    "Processes": [
        [
            "nukelab",
            "1",
            "0.1",
            "0.5",
            "1000000",
            "200000",
            "?",
            "Ss",
            "10:00",
            "0:03",
            "/sbin/init",
        ],
        [
            "nukelab",
            "42",
            "25.4",
            "10.2",
            "8000000",
            "4000000",
            "?",
            "R",
            "10:01",
            "1:12",
            "python sim.py",
        ],
    ],
}


class TestServerTasks:
    @pytest.mark.asyncio
    async def test_tasks_running_server(self, client, user_token, test_user, db_session):
        """Running server returns normalized task dicts."""
        server = Server(name="srv-tasks", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_top = mock.AsyncMock(return_value=TOP_PAYLOAD)
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{server.id}/tasks",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert len(data["tasks"]) == 2

        first = data["tasks"][0]
        assert first["pid"] == 1
        assert first["user"] == "nukelab"
        assert first["cpu_percent"] == 0.1
        assert first["mem_percent"] == 0.5
        assert first["rss_bytes"] == 200000 * 1024  # ps RSS is KiB
        assert first["stat"] == "Ss"
        assert first["time"] == "0:03"
        assert first["cpu_time_seconds"] == 3
        assert first["command"] == "/sbin/init"

        second = data["tasks"][1]
        assert second["cpu_time_seconds"] == 72  # "1:12"

        mock_client.get_container_top.assert_awaited_once_with("c1", ps_args="aux")

    @pytest.mark.asyncio
    async def test_tasks_parses_day_format_time(self, client, user_token, test_user, db_session):
        """ps TIME beyond 24h uses dd-hh:mm:ss and must parse to seconds."""
        server = Server(
            name="srv-tasks-days", user_id=test_user.id, status="running", container_id="c1"
        )
        db_session.add(server)
        await db_session.commit()

        payload = {
            **TOP_PAYLOAD,
            "Processes": [
                [
                    "nukelab",
                    "9",
                    "1.0",
                    "1.0",
                    "1000",
                    "1000",
                    "?",
                    "S",
                    "10:01",
                    "1-02:03:04",
                    "long-sim",
                ]
            ],
        }
        mock_client = mock.MagicMock()
        mock_client.get_container_top = mock.AsyncMock(return_value=payload)
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{server.id}/tasks",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        task = response.json()["tasks"][0]
        assert task["cpu_time_seconds"] == 86400 + 2 * 3600 + 3 * 60 + 4

    @pytest.mark.asyncio
    async def test_tasks_tolerates_short_rows(self, client, user_token, test_user, db_session):
        """Rows shorter than Titles get defaults instead of failing."""
        server = Server(
            name="srv-tasks-short", user_id=test_user.id, status="running", container_id="c1"
        )
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_top = mock.AsyncMock(
            return_value={**TOP_PAYLOAD, "Processes": [["nukelab", "7"]]}
        )
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{server.id}/tasks",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        task = response.json()["tasks"][0]
        assert task["pid"] == 7
        assert task["cpu_percent"] == 0.0
        assert task["command"] == ""

    @pytest.mark.asyncio
    async def test_tasks_stopped_server(self, client, user_token, test_user, db_session):
        """Stopped server (no container) returns an empty list."""
        server = Server(
            name="srv-tasks-stop", user_id=test_user.id, status="stopped", container_id=None
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}/tasks",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_tasks_driver_error(self, client, user_token, test_user, db_session):
        """Runtime errors degrade to an empty list with status=error."""
        server = Server(
            name="srv-tasks-err", user_id=test_user.id, status="running", container_id="c1"
        )
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_top = mock.AsyncMock(
            side_effect=ContainerDriverError("not found", status=404)
        )
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{server.id}/tasks",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_tasks_forbidden_for_non_owner(self, client, user_token, admin_user, db_session):
        """Regular users cannot list tasks of another user's server."""
        server = Server(
            name="srv-tasks-other", user_id=admin_user.id, status="running", container_id="c1"
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}/tasks",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 403
