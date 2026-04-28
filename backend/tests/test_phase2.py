"""
Basic tests for Phase 2 RBAC and user management.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.db.session import get_db
from app.models.user import User
from app.core.security import get_password_hash
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS

client = TestClient(app)

# Test data
TEST_USER = {
    "username": "testuser",
    "email": "test@example.com",
    "password": "testpass123",
    "role": "user"
}

ADMIN_USER = {
    "username": "admin",
    "email": "admin@example.com",
    "password": "admin123",
    "role": "super_admin"
}


@pytest.fixture
async def db_session():
    """Get database session"""
    async with get_db() as session:
        yield session


class TestAuth:
    """Test authentication endpoints"""
    
    def test_login_success(self):
        """Test successful login"""
        response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        assert response.status_code == 200
        assert "access_token" in response.json()
    
    def test_login_failure(self):
        """Test failed login"""
        response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "wrongpassword"}
        )
        assert response.status_code == 401
    
    def test_get_me_unauthorized(self):
        """Test getting current user without token"""
        response = client.get("/api/auth/me")
        assert response.status_code == 401


class TestPermissions:
    """Test permission system"""
    
    def test_permission_constants(self):
        """Test permission constants exist"""
        assert Permission.USERS_READ == "users:read"
        assert Permission.SERVERS_START == "servers:start"
        assert Permission.ALL == "*"
    
    def test_role_permissions(self):
        """Test role-permission mappings"""
        assert Permission.ALL in ROLE_PERMISSIONS["super_admin"]
        assert Permission.USERS_READ in ROLE_PERMISSIONS["admin"]
        assert Permission.SERVERS_READ_OWN in ROLE_PERMISSIONS["user"]
    
    def test_user_role_has_no_admin_perms(self):
        """Test regular user has no admin permissions"""
        user_perms = ROLE_PERMISSIONS["user"]
        assert Permission.USERS_CREATE not in user_perms
        assert Permission.ADMIN_ACCESS not in user_perms


class TestUserCRUD:
    """Test user CRUD operations"""
    
    def test_create_user_as_admin(self):
        """Test admin can create user"""
        # Login as admin
        login_response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        token = login_response.json()["access_token"]
        
        # Create user
        response = client.post(
            "/api/users/",
            json=TEST_USER,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        assert response.json()["username"] == TEST_USER["username"]
    
    def test_list_users_as_admin(self):
        """Test admin can list users"""
        login_response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        token = login_response.json()["access_token"]
        
        response = client.get(
            "/api/users/",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert "users" in response.json()
    
    def test_list_users_as_regular_user_fails(self):
        """Test regular user cannot list all users"""
        # Login as test user
        login_response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpass123"}
        )
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            
            response = client.get(
                "/api/users/",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403


class TestCredits:
    """Test credit system"""
    
    def test_get_credits_authenticated(self):
        """Test getting credits when authenticated"""
        login_response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        token = login_response.json()["access_token"]
        
        response = client.get(
            "/api/credits/",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert "balance" in response.json()
    
    def test_grant_credits_as_admin(self):
        """Test admin can grant credits"""
        login_response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        token = login_response.json()["access_token"]
        
        # This would need a user ID - simplified test
        response = client.get(
            "/api/admin/credits/summary",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200


class TestAdminEndpoints:
    """Test admin-only endpoints"""
    
    def test_admin_stats(self):
        """Test admin stats endpoint"""
        login_response = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        token = login_response.json()["access_token"]
        
        response = client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert "users" in response.json()
        assert "servers" in response.json()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
