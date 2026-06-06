"""Coverage tests for app/db/session.py."""

import pytest
from unittest import mock


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
