# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the schema-compatibility guard."""

from unittest import mock

import pytest


class FakeScript:
    def __init__(self, revision):
        self.revision = revision


def _make_engine(rows=None, execute_side_effect=None):
    """Return a mocked async engine yielding the given query rows."""
    mock_conn = mock.AsyncMock()
    if execute_side_effect is not None:
        mock_conn.execute.side_effect = execute_side_effect
    else:
        mock_conn.execute.return_value = rows or []
    mock_conn.__aenter__.return_value = mock_conn
    mock_conn.__aexit__.return_value = False

    engine = mock.AsyncMock()
    engine.connect = mock.MagicMock(return_value=mock_conn)
    return engine


class TestCheckSchemaCompatibility:
    """Tests for app.db.schema_guard.check_schema_compatibility."""

    @pytest.mark.asyncio
    async def test_known_revision_passes(self):
        """A DB revision present in the local ScriptDirectory is compatible."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(rows=[("abc123",)])

        with mock.patch(
            "app.db.schema_guard.ScriptDirectory"
        ) as mock_script_dir_cls:
            mock_script_dir_cls.return_value.walk_revisions.return_value = [
                FakeScript("abc123")
            ]
            result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is True
        assert result.unknown_revisions == ()
        assert result.db_revisions == ("abc123",)
        assert "abc123" in result.known_revisions

    @pytest.mark.asyncio
    async def test_unknown_revision_detected(self):
        """A DB revision absent from ScriptDirectory is a rollback hazard."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(rows=[("newer_rev",)])

        with mock.patch(
            "app.db.schema_guard.ScriptDirectory"
        ) as mock_script_dir_cls:
            mock_script_dir_cls.return_value.walk_revisions.return_value = [
                FakeScript("abc123")
            ]
            result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is False
        assert result.unknown_revisions == ("newer_rev",)

    @pytest.mark.asyncio
    async def test_multiple_db_revisions_all_known(self):
        """Multiple known DB revisions are compatible."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(rows=[("rev1",), ("rev2",)])

        with mock.patch(
            "app.db.schema_guard.ScriptDirectory"
        ) as mock_script_dir_cls:
            mock_script_dir_cls.return_value.walk_revisions.return_value = [
                FakeScript("rev1"),
                FakeScript("rev2"),
            ]
            result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is True
        assert result.db_revisions == ("rev1", "rev2")

    @pytest.mark.asyncio
    async def test_no_alembic_version_table_is_fresh_db(self):
        """Missing alembic_version table means fresh/unmanaged DB: compatible."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(
            execute_side_effect=Exception(
                "relation 'alembic_version' does not exist"
            )
        )

        result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is True
        assert result.db_unreachable is True
        assert result.db_revisions == ()

    @pytest.mark.asyncio
    async def test_empty_alembic_version_is_fresh_db(self):
        """Empty alembic_version table is treated as fresh/unmanaged."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(rows=[])

        result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is True
        assert result.db_revisions == ()

    @pytest.mark.asyncio
    async def test_script_directory_failure_does_not_block_startup(self):
        """Failure to load the Alembic script directory is logged, not fatal."""
        from app.db.schema_guard import check_schema_compatibility

        engine = _make_engine(rows=[("abc123",)])

        with mock.patch(
            "app.db.schema_guard.ScriptDirectory",
            side_effect=Exception("corrupt env.py"),
        ):
            result = await check_schema_compatibility(engine, "/app/alembic")

        assert result.ok is True
        assert result.db_revisions == ("abc123",)


class TestRunSchemaGuard:
    """Tests for app.db.schema_guard.run_schema_guard decision logic."""

    @pytest.mark.asyncio
    async def test_known_revision_passes_all_modes(self):
        """No-op when the DB revision is known."""
        from app.db.schema_guard import run_schema_guard

        engine = mock.AsyncMock()
        with mock.patch(
            "app.db.schema_guard.check_schema_compatibility",
            return_value=mock.Mock(ok=True, unknown_revisions=()),
        ):
            await run_schema_guard(engine, "/app/alembic", "enforce", "production")
            await run_schema_guard(engine, "/app/alembic", "auto", "production")
            await run_schema_guard(engine, "/app/alembic", "off", "production")

    @pytest.mark.asyncio
    async def test_unknown_revision_refuses_in_enforce_mode(self):
        """enforce mode always refuses an unknown DB revision."""
        from app.db.schema_guard import run_schema_guard

        engine = mock.AsyncMock()
        with mock.patch(
            "app.db.schema_guard.check_schema_compatibility",
            return_value=mock.Mock(
                ok=False, unknown_revisions=("newer_rev",), db_revisions=("newer_rev",)
            ),
        ):
            with pytest.raises(RuntimeError, match="newer_rev"):
                await run_schema_guard(engine, "/app/alembic", "enforce", "development")

    @pytest.mark.asyncio
    async def test_unknown_revision_refuses_in_production_auto(self):
        """auto mode refuses an unknown DB revision in production."""
        from app.db.schema_guard import run_schema_guard

        engine = mock.AsyncMock()
        with mock.patch(
            "app.db.schema_guard.check_schema_compatibility",
            return_value=mock.Mock(
                ok=False, unknown_revisions=("newer_rev",), db_revisions=("newer_rev",)
            ),
        ):
            with pytest.raises(RuntimeError, match="newer_rev"):
                await run_schema_guard(engine, "/app/alembic", "auto", "production")

    @pytest.mark.asyncio
    async def test_unknown_revision_warns_in_non_production_auto(self):
        """auto mode warns in non-production environments."""
        from app.db.schema_guard import run_schema_guard

        engine = mock.AsyncMock()
        with mock.patch(
            "app.db.schema_guard.check_schema_compatibility",
            return_value=mock.Mock(
                ok=False, unknown_revisions=("newer_rev",), db_revisions=("newer_rev",)
            ),
        ), mock.patch("app.db.schema_guard.logger") as mock_logger:
            await run_schema_guard(engine, "/app/alembic", "auto", "development")

        mock_logger.warning.assert_called_once()
        assert "newer_rev" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_off_mode_does_not_raise_or_warn(self):
        """off mode skips the guard entirely."""
        from app.db.schema_guard import run_schema_guard

        engine = mock.AsyncMock()
        with mock.patch(
            "app.db.schema_guard.check_schema_compatibility"
        ) as mock_check, mock.patch("app.db.schema_guard.logger") as mock_logger:
            await run_schema_guard(engine, "/app/alembic", "off", "production")

        mock_check.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()


class TestSettingsValidation:
    """Tests for the DB_SCHEMA_GUARD setting validation."""

    @pytest.mark.parametrize("mode", ["off", "auto", "enforce"])
    def test_valid_db_schema_guard_values(self, mode):
        """off/auto/enforce are accepted."""
        from app.config import Settings

        settings = Settings(db_schema_guard=mode)
        assert settings.db_schema_guard == mode

    def test_invalid_db_schema_guard_value_rejected(self):
        """An unsupported value is rejected at settings construction time."""
        from app.config import Settings

        with pytest.raises(ValueError, match="DB_SCHEMA_GUARD"):
            Settings(db_schema_guard="warn-only")
