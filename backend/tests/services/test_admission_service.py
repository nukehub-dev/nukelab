# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.admission_service import ADMISSION_LOCK_KEY, acquire_admission_lock


@pytest.mark.asyncio
async def test_admission_rejects_missing_transaction():
    db = MagicMock(in_transaction=MagicMock(return_value=False), execute=AsyncMock())
    with pytest.raises(RuntimeError, match="caller-owned"):
        await acquire_admission_lock(db)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_admission_rejects_stale_snapshot_isolation():
    connection = MagicMock(get_isolation_level=AsyncMock(return_value="REPEATABLE READ"))
    db = MagicMock(
        in_transaction=MagicMock(return_value=True),
        connection=AsyncMock(return_value=connection),
        execute=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="READ COMMITTED"):
        await acquire_admission_lock(db)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_is_a_separate_statement_without_committing():
    connection = MagicMock(get_isolation_level=AsyncMock(return_value="READ COMMITTED"))
    db = MagicMock(
        in_transaction=MagicMock(return_value=True),
        connection=AsyncMock(return_value=connection),
        execute=AsyncMock(),
        commit=AsyncMock(),
    )
    await acquire_admission_lock(db)
    statement, parameters = db.execute.call_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(:key)"
    assert parameters == {"key": ADMISSION_LOCK_KEY}
    db.commit.assert_not_awaited()
