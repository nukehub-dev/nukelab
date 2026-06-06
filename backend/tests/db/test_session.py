"""Coverage tests for app/db/session.py."""

import pytest
from unittest import mock


class TestEngineConfiguration:
    """Tests that the async engine is created with correct pool settings."""

    def test_create_async_engine_receives_all_pool_settings(self):
        """Engine must be created with pool_size, max_overflow, timeout, recycle, pre_ping, and connect_args."""
        from app.config import settings

        # Patch at the sqlalchemy source *before* importing session.py so the
        # module-level `engine = create_async_engine(...)` call is captured.
        with mock.patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create:
            mock_create.return_value = mock.Mock()

            import importlib
            # Ensure session.py is not already imported in this process
            import sys
            for mod in list(sys.modules.keys()):
                if mod.startswith("app.db.session"):
                    del sys.modules[mod]
            # Also clear config cache so settings reload inside session.py
            for mod in list(sys.modules.keys()):
                if mod == "app.config":
                    del sys.modules[mod]

            import app.db.session as session_module  # noqa: F401

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs

            assert call_kwargs["pool_size"] == settings.database_pool_size
            assert call_kwargs["max_overflow"] == settings.database_pool_max_overflow
            assert call_kwargs["pool_timeout"] == settings.database_pool_timeout
            assert call_kwargs["pool_recycle"] == settings.database_pool_recycle
            assert call_kwargs["pool_pre_ping"] == settings.database_pool_pre_ping
            assert call_kwargs["connect_args"] == {
                "command_timeout": settings.database_query_timeout_seconds,
            }

    def test_create_async_engine_uses_expected_values(self):
        """Engine creation must pass all configured values through."""
        from app.config import settings

        with mock.patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create:
            mock_create.return_value = mock.Mock()

            import sys
            for mod in list(sys.modules.keys()):
                if mod.startswith("app.db.session"):
                    del sys.modules[mod]
            for mod in list(sys.modules.keys()):
                if mod == "app.config":
                    del sys.modules[mod]

            import app.db.session as session_module  # noqa: F401

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["pool_size"] == settings.database_pool_size
            assert call_kwargs["max_overflow"] == settings.database_pool_max_overflow
            assert call_kwargs["pool_timeout"] == settings.database_pool_timeout
            assert call_kwargs["pool_recycle"] == settings.database_pool_recycle
            assert call_kwargs["pool_pre_ping"] == settings.database_pool_pre_ping
            assert call_kwargs["connect_args"] == {
                "command_timeout": settings.database_query_timeout_seconds,
            }


class TestGetDb:
    """Tests for get_db generator."""

    @pytest.mark.asyncio
    async def test_get_db_rollback_on_exception(self):
        """Should rollback when exception occurs inside context."""
        from app.db.session import get_db

        mock_session = mock.AsyncMock()
        mock_session.commit = mock.AsyncMock(side_effect=RuntimeError("db error"))
        mock_session.rollback = mock.AsyncMock()
        mock_session.close = mock.AsyncMock()

        with mock.patch("app.db.session.AsyncSessionLocal") as mock_factory:
            mock_factory.return_value.__aenter__ = mock.AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            gen = get_db()
            db = await gen.__anext__()
            assert db is mock_session

            # Simulate exception being thrown inside the context
            try:
                await gen.athrow(RuntimeError, RuntimeError("db error"))
            except RuntimeError:
                pass

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()
