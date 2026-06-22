"""Diagnostic test to detect cross-test DB leakage."""

import pytest
from sqlalchemy import select

from app.models.user import User
from app.models.volume import Volume
from app.models.server import Server
from app.models.maintenance_window import MaintenanceWindow


@pytest.mark.asyncio
async def test_diagnostic_counts(db_session):
    """Fail if earlier tests left records behind."""
    u = (await db_session.execute(select(User))).scalars().all()
    v = (await db_session.execute(select(Volume))).scalars().all()
    s = (await db_session.execute(select(Server))).scalars().all()
    m = (await db_session.execute(select(MaintenanceWindow))).scalars().all()
    msg = f"\n[DIAGNOSTIC] users={len(u)} volumes={len(v)} servers={len(s)} maint={len(m)}"
    print(msg)
    assert len(u) == 0 and len(v) == 0 and len(s) == 0 and len(m) == 0, msg
