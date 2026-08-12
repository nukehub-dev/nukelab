# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Credit Requests API endpoints."""

import uuid as uuid_mod

import pytest


class TestCreditRequestUserEndpoints:
    """User-facing credit request endpoints."""

    @pytest.mark.asyncio
    async def test_create_credit_request(self, client, user_token):
        """User should be able to create a credit request."""
        response = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 100, "reason": "Running a big simulation"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["request"]["status"] == "pending"
        assert data["request"]["amount"] == 100

    @pytest.mark.asyncio
    async def test_create_credit_request_validation(self, client, user_token):
        """Invalid bodies should be rejected with 422."""
        response = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 0, "reason": "no credits"},
        )
        assert response.status_code == 422

        response = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": ""},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_pending_request_rejected(self, client, user_token):
        """A second pending request should return 400."""
        headers = {"Authorization": f"Bearer {user_token}"}
        body = {"amount": 50, "reason": "first"}
        response = await client.post("/api/credit-requests/", headers=headers, json=body)
        assert response.status_code == 200

        response = await client.post(
            "/api/credit-requests/", headers=headers, json={"amount": 75, "reason": "second"}
        )
        assert response.status_code == 400
        assert "open credit request" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_own_requests(self, client, user_token, test_user):
        """User should see only their own requests."""
        headers = {"Authorization": f"Bearer {user_token}"}
        await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "mine"},
        )

        response = await client.get("/api/credit-requests/", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        assert all(r["user_id"] == str(test_user.id) for r in data["requests"])

    @pytest.mark.asyncio
    async def test_list_own_status_filter(self, client, user_token):
        """Status filter should apply to the user's own list."""
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.get("/api/credit-requests/?status=approved", headers=headers)
        assert response.status_code == 200
        assert all(r["status"] == "approved" for r in response.json()["requests"])


class TestCreditRequestAdminEndpoints:
    """Admin review endpoints."""

    @pytest.mark.asyncio
    async def test_admin_can_list_all(self, client, admin_token, user_token):
        """Admin should list all requests with user details."""
        await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 25, "reason": "for admin list"},
        )
        response = await client.get(
            "/api/credit-requests/all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        assert "username" in data["requests"][0]
        assert "email" in data["requests"][0]

    @pytest.mark.asyncio
    async def test_admin_can_get_pending_count(self, client, admin_token, user_token):
        """Admin should read the pending count."""
        await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 25, "reason": "count"},
        )
        response = await client.get(
            "/api/credit-requests/pending-count",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["pending"] >= 1

    @pytest.mark.asyncio
    async def test_admin_can_approve(self, client, admin_token, user_token, test_user, db_session):
        """Admin approval should grant credits to the requesting user."""
        from app.services.credit_service import CreditService

        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 60, "reason": "approve me"},
        )
        request_id = create.json()["request"]["id"]
        initial = await CreditService(db_session).get_balance(str(test_user.id))

        response = await client.post(
            f"/api/credit-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["request"]["status"] == "approved"
        assert data["request"]["granted_amount"] == 60
        assert "60" in data["message"]
        assert await CreditService(db_session).get_balance(str(test_user.id)) == initial + 60

    @pytest.mark.asyncio
    async def test_admin_can_approve_with_adjusted_amount(
        self, client, admin_token, user_token, test_user, db_session
    ):
        """Admin approval should honor an adjusted amount."""
        from app.services.credit_service import CreditService

        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 100, "reason": "adjust"},
        )
        request_id = create.json()["request"]["id"]
        initial = await CreditService(db_session).get_balance(str(test_user.id))

        response = await client.post(
            f"/api/credit-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"amount": 30, "note": "partial approval"},
        )
        assert response.status_code == 200
        assert response.json()["request"]["granted_amount"] == 30
        assert await CreditService(db_session).get_balance(str(test_user.id)) == initial + 30

    @pytest.mark.asyncio
    async def test_admin_can_reject(self, client, admin_token, user_token, test_user, db_session):
        """Admin rejection should not grant credits."""
        from app.services.credit_service import CreditService

        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 60, "reason": "reject me"},
        )
        request_id = create.json()["request"]["id"]
        initial = await CreditService(db_session).get_balance(str(test_user.id))

        response = await client.post(
            f"/api/credit-requests/{request_id}/reject",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"note": "Insufficient justification"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["request"]["status"] == "rejected"
        assert data["request"]["review_note"] == "Insufficient justification"
        assert await CreditService(db_session).get_balance(str(test_user.id)) == initial

    @pytest.mark.asyncio
    async def test_review_unknown_request_returns_404(self, client, admin_token):
        """Reviewing an unknown request should return 404."""
        unknown = str(uuid_mod.uuid4())
        response = await client.post(
            f"/api/credit-requests/{unknown}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        assert response.status_code == 404

        response = await client.post(
            f"/api/credit-requests/{unknown}/reject",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_review_non_pending_returns_400(self, client, admin_token, user_token):
        """Reviewing an already-resolved request should return 400."""
        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": "resolve twice"},
        )
        request_id = create.json()["request"]["id"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        response = await client.post(
            f"/api/credit-requests/{request_id}/approve", headers=headers, json={}
        )
        assert response.status_code == 200

        response = await client.post(
            f"/api/credit-requests/{request_id}/approve", headers=headers, json={}
        )
        assert response.status_code == 400

        response = await client.post(
            f"/api/credit-requests/{request_id}/reject", headers=headers, json={}
        )
        assert response.status_code == 400


class TestCreditRequestAuthorization:
    """Regular users must not access admin endpoints."""

    @pytest.mark.asyncio
    async def test_user_forbidden_from_list_all(self, client, user_token):
        response = await client.get(
            "/api/credit-requests/all",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_forbidden_from_pending_count(self, client, user_token):
        response = await client.get(
            "/api/credit-requests/pending-count",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_forbidden_from_approve_and_reject(self, client, user_token, test_user):
        request_id = str(uuid_mod.uuid4())
        headers = {"Authorization": f"Bearer {user_token}"}

        response = await client.post(
            f"/api/credit-requests/{request_id}/approve", headers=headers, json={}
        )
        assert response.status_code == 403

        response = await client.post(
            f"/api/credit-requests/{request_id}/reject", headers=headers, json={}
        )
        assert response.status_code == 403


class TestCreditRequestOpenFilter:
    """status=open query covers pending + needs_info."""

    @pytest.mark.asyncio
    async def test_list_own_open_filter(self, client, user_token, admin_token):
        headers = {"Authorization": f"Bearer {user_token}"}
        create = await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "open filter"},
        )
        request_id = create.json()["request"]["id"]

        # Reviewer message flips to needs_info; still "open"
        await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"body": "which project?"},
        )

        response = await client.get("/api/credit-requests/?status=open", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 1
        assert data["requests"][0]["status"] == "needs_info"

    @pytest.mark.asyncio
    async def test_list_all_open_filter(self, client, admin_token, user_token):
        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": "admin open filter"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.get(
            "/api/credit-requests/all?status=open",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert any(r["id"] == request_id for r in response.json()["requests"])


class TestCreditRequestMessagesAPI:
    """Conversation endpoints."""

    @pytest.mark.asyncio
    async def test_user_posts_and_reads_own_thread(self, client, user_token):
        headers = {"Authorization": f"Bearer {user_token}"}
        create = await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "chat"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers=headers,
            json={"body": "any update?"},
        )
        assert response.status_code == 200
        assert response.json()["message"]["body"] == "any update?"

        response = await client.get(f"/api/credit-requests/{request_id}/messages", headers=headers)
        assert response.status_code == 200
        messages = response.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["is_admin"] is False

    @pytest.mark.asyncio
    async def test_reviewer_posts_and_state_flips(self, client, user_token, admin_token):
        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": "reviewer chat"},
        )
        request_id = create.json()["request"]["id"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        response = await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers=admin_headers,
            json={"body": "please clarify"},
        )
        assert response.status_code == 200

        # Request now needs_info; visible in the admin list
        response = await client.get(
            "/api/credit-requests/all?status=needs_info", headers=admin_headers
        )
        assert any(r["id"] == request_id for r in response.json()["requests"])

        # Reviewer reads the thread with is_admin flags
        response = await client.get(
            f"/api/credit-requests/{request_id}/messages", headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["messages"][0]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_user_cannot_post_on_others_request(self, client, user_token, db_session):
        """A regular user gets 403 posting on someone else's request."""
        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": "not yours"},
        )
        request_id = create.json()["request"]["id"]

        from app.api.auth import create_access_token
        from app.models.user import User

        other = User(
            username="otheruser",
            email="other@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()
        other_token = create_access_token(data={"sub": other.username, "role": other.role})

        response = await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"body": "intruding"},
        )
        assert response.status_code == 403

        response = await client.get(
            f"/api/credit-requests/{request_id}/messages",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_post_on_terminal_request_returns_400(self, client, user_token, admin_token):
        headers = {"Authorization": f"Bearer {user_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        create = await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "terminal post"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.post(
            f"/api/credit-requests/{request_id}/reject",
            headers=admin_headers,
            json={},
        )
        assert response.status_code == 200

        response = await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers=headers,
            json={"body": "hello?"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_post_message_validation(self, client, user_token):
        headers = {"Authorization": f"Bearer {user_token}"}
        create = await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "validation"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.post(
            f"/api/credit-requests/{request_id}/messages",
            headers=headers,
            json={"body": ""},
        )
        assert response.status_code == 422


class TestCreditRequestCancelAPI:
    """Cancel endpoint."""

    @pytest.mark.asyncio
    async def test_user_cancels_own_request(self, client, user_token):
        headers = {"Authorization": f"Bearer {user_token}"}
        create = await client.post(
            "/api/credit-requests/",
            headers=headers,
            json={"amount": 10, "reason": "cancel me"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.post(f"/api/credit-requests/{request_id}/cancel", headers=headers)
        assert response.status_code == 200
        assert response.json()["request"]["status"] == "cancelled"

        # Cancelling again hits the terminal-state guard
        response = await client.post(f"/api/credit-requests/{request_id}/cancel", headers=headers)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_cannot_cancel_users_request(self, client, user_token, admin_token):
        create = await client.post(
            "/api/credit-requests/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 10, "reason": "hands off"},
        )
        request_id = create.json()["request"]["id"]

        response = await client.post(
            f"/api/credit-requests/{request_id}/cancel",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
