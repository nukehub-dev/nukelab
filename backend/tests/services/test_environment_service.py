"""Tests for EnvironmentService business logic."""

import pytest
import uuid as uuid_mod

from sqlalchemy import select

from app.services.environment_service import EnvironmentService
from app.models.environment_template import EnvironmentTemplate


class TestEnvironmentServiceGetById:
    """Tests for get_by_id."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, db_session):
        """get_by_id should return environment when found."""
        env = EnvironmentTemplate(name="Test Env", slug="test-env", image="test:latest")
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        result = await service.get_by_id(str(env.id))
        assert result is not None
        assert result.name == "Test Env"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session):
        """get_by_id should return None when not found."""
        service = EnvironmentService(db_session)
        result = await service.get_by_id(str(uuid_mod.uuid4()))
        assert result is None


class TestEnvironmentServiceList:
    """Tests for list_environments."""

    @pytest.mark.asyncio
    async def test_list_environments_no_filters(self, db_session):
        """Should return all environments."""
        env1 = EnvironmentTemplate(name="Env 1", slug="env-1", image="img1")
        env2 = EnvironmentTemplate(name="Env 2", slug="env-2", image="img2")
        db_session.add_all([env1, env2])
        await db_session.commit()

        service = EnvironmentService(db_session)
        result = await service.list_environments()
        assert result["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_environments_active_only(self, db_session):
        """Should filter by is_active."""
        env = EnvironmentTemplate(name="Inactive", slug="inactive", image="img", is_active=False)
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        result = await service.list_environments(is_active=True)
        slugs = [e["slug"] for e in result["items"]]
        assert "inactive" not in slugs

    @pytest.mark.asyncio
    async def test_list_environments_search(self, db_session):
        """Should search by name."""
        env = EnvironmentTemplate(name="Searchable", slug="search", image="img")
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        result = await service.list_environments(search="Searchable")
        assert len(result["items"]) >= 1


class TestEnvironmentServiceCreate:
    """Tests for create_environment."""

    @pytest.mark.asyncio
    async def test_create_environment_success(self, db_session):
        """Should create a new environment."""
        service = EnvironmentService(db_session)
        env = await service.create_environment(
            name="New Env", slug="new-env", image="new:latest", description="A new environment"
        )
        assert env.name == "New Env"
        assert env.slug == "new-env"

    @pytest.mark.asyncio
    async def test_create_environment_duplicate_slug(self, db_session):
        """Should reject duplicate slug."""
        env = EnvironmentTemplate(name="Existing", slug="dup-env", image="img")
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_environment(name="Dup", slug="dup-env", image="img")
        assert "already exists" in str(exc_info.value)


class TestEnvironmentServiceUpdate:
    """Tests for update_environment."""

    @pytest.mark.asyncio
    async def test_update_environment_success(self, db_session):
        """Should update environment fields."""
        env = EnvironmentTemplate(name="Old", slug="upd-env", image="img")
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        updated = await service.update_environment(str(env.id), name="New", description="Updated")
        assert updated.name == "New"
        assert updated.description == "Updated"

    @pytest.mark.asyncio
    async def test_update_environment_not_found(self, db_session):
        """Should raise when environment not found."""
        service = EnvironmentService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.update_environment(str(uuid_mod.uuid4()), name="X")
        assert "not found" in str(exc_info.value)


class TestEnvironmentServiceDelete:
    """Tests for delete_environment."""

    @pytest.mark.asyncio
    async def test_delete_environment_success(self, db_session):
        """Should delete environment."""
        env = EnvironmentTemplate(name="To Delete", slug="del-env", image="img")
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        await service.delete_environment(str(env.id))

        result = await db_session.execute(
            select(EnvironmentTemplate).where(EnvironmentTemplate.id == env.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_environment_not_found(self, db_session):
        """Should raise when environment not found."""
        service = EnvironmentService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.delete_environment(str(uuid_mod.uuid4()))
        assert "not found" in str(exc_info.value)


class TestEnvironmentServiceClone:
    """Tests for clone_environment."""

    @pytest.mark.asyncio
    async def test_clone_environment(self, db_session):
        """Should create a copy with new slug."""
        env = EnvironmentTemplate(
            name="Original", slug="orig-env", image="img", description="Desc", packages=["pkg1"]
        )
        db_session.add(env)
        await db_session.commit()

        service = EnvironmentService(db_session)
        cloned = await service.clone_environment(
            str(env.id), new_name="Cloned", new_slug="cloned-env"
        )
        assert cloned.name == "Cloned"
        assert cloned.slug == "cloned-env"
        assert cloned.image == "img"
        assert cloned.packages == ["pkg1"]
