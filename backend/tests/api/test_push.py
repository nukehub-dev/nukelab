# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Web Push subscription endpoints."""

import pytest

from app.models.push_subscription import PushSubscription


class TestVapidPublicKey:
    @pytest.mark.asyncio
    async def test_returns_public_key_when_configured(self, client, user_token, monkeypatch):
        monkeypatch.setattr("app.api.push.settings.vapid_public_key", "test-public-key")
        response = await client.get(
            "/api/push/vapid-public-key", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["public_key"] == "test-public-key"

    @pytest.mark.asyncio
    async def test_404_when_unconfigured(self, client, user_token, monkeypatch):
        monkeypatch.setattr("app.api.push.settings.vapid_public_key", "")
        response = await client.get(
            "/api/push/vapid-public-key", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestPushSubscriptions:
    @pytest.mark.asyncio
    async def test_subscribe_stores_subscription(self, client, user_token, test_user, db_session):
        response = await client.post(
            "/api/push/subscriptions",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "endpoint": "https://push.example.com/sub-1",
                "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["endpoint"] == "https://push.example.com/sub-1"

    @pytest.mark.asyncio
    async def test_subscribe_upserts_existing_endpoint(
        self, client, user_token, test_user, db_session
    ):
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/sub-1",
            keys={"p256dh": "old", "auth": "old"},
        )
        db_session.add(sub)
        await db_session.commit()

        response = await client.post(
            "/api/push/subscriptions",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "endpoint": "https://push.example.com/sub-1",
                "keys": {"p256dh": "new", "auth": "new"},
            },
        )
        assert response.status_code == 201

        result = await db_session.execute(
            select(PushSubscription).where(PushSubscription.id == sub.id)
        )
        updated = result.scalar_one()
        assert updated.keys["p256dh"] == "new"

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(
        self, client, user_token, test_user, db_session
    ):
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/sub-1",
            keys={"p256dh": "p256dh", "auth": "auth"},
        )
        db_session.add(sub)
        await db_session.commit()

        response = await client.delete(
            "/api/push/subscriptions?endpoint=https://push.example.com/sub-1",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 204

        result = await db_session.execute(
            select(PushSubscription).where(PushSubscription.id == sub.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_unsubscribe_does_not_remove_other_users(
        self, client, user_token, test_user, db_session
    ):
        from app.models.user import User

        other = User(username="other-push", email="other-push@example.com", password_hash="x")
        db_session.add(other)
        await db_session.commit()
        sub = PushSubscription(
            user_id=other.id,
            endpoint="https://push.example.com/sub-1",
            keys={"p256dh": "p256dh", "auth": "auth"},
        )
        db_session.add(sub)
        await db_session.commit()

        response = await client.delete(
            "/api/push/subscriptions?endpoint=https://push.example.com/sub-1",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 204

        result = await db_session.execute(
            select(PushSubscription).where(PushSubscription.id == sub.id)
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_subscribe_recovers_from_concurrent_insert_race(
        self, client, user_token, test_user, db_session, monkeypatch
    ):
        """A concurrent subscribe winning the insert race must not 500.

        The unique (user_id, endpoint) index fires on the losing insert; the
        endpoint should roll back and update the winning row instead.
        """
        # The row a "concurrent" request already inserted.
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/race",
            keys={"p256dh": "old", "auth": "old"},
        )
        db_session.add(sub)
        await db_session.commit()
        sub_id = str(sub.id)  # capture now; the endpoint's rollback expires `sub`

        # Simulate the race: the endpoint's pre-check SELECT misses the row,
        # so it proceeds to INSERT and hits the unique index.
        original_execute = db_session.execute
        missed = False

        async def racy_execute(statement, *args, **kwargs):
            nonlocal missed
            if not missed and "push_subscriptions" in str(statement):
                missed = True
                return await original_execute(
                    select(PushSubscription).where(PushSubscription.id.is_(None))
                )
            return await original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "execute", racy_execute)

        response = await client.post(
            "/api/push/subscriptions",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "endpoint": "https://push.example.com/race",
                "keys": {"p256dh": "new", "auth": "new"},
            },
        )
        assert response.status_code == 201
        assert response.json()["id"] == sub_id

        await db_session.refresh(sub)
        assert sub.keys["p256dh"] == "new"


# Import select locally to avoid circular imports at module load time.
from sqlalchemy import select
