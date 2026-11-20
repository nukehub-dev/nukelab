# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Transaction-owned serialization for platform allocation and name admission."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Stable domain key, shared by all allocators; transaction pooling is supported.
ADMISSION_LOCK_KEY = 0x4E554B454C4142


async def acquire_admission_lock(db: AsyncSession) -> None:
    """Lock before fresh policy/accounting queries in a caller-owned transaction.

    Callers must persist reservations before committing and must never invoke a
    helper that commits inside this critical section. External runtime work starts
    after commit. This primitive alone does not reserve capacity.
    """
    if not db.in_transaction():
        raise RuntimeError("Admission requires a caller-owned transaction")
    connection = await db.connection()
    if await connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("Admission requires READ COMMITTED isolation")
    # Keep acquisition separate from accounting: the lock can wait while another
    # transaction commits, so its statement snapshot cannot supply fresh counts.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMISSION_LOCK_KEY})
