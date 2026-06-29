#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Pre-seed the database with test users for load testing.

Run this *before* starting Locust/k6 so the load tests can log in
without hitting API rate limits on registration.

Usage:
    cd backend && python -m tests.load.setup_test_data --users 100

Or inside the backend container:
    docker compose exec backend python -m tests.load.setup_test_data --users 100
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

# Ensure backend is on path
sys.path.insert(0, ".")

from app.core.security import get_password_hash
from app.models.user import User

TEST_PASSWORD = "LoadTest123!"


async def create_test_users(count: int) -> list[str]:
    """Create N test users with known credentials."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username.like("loadtest_%")))
        existing = result.scalars().all()
        existing_usernames = {u.username for u in existing}
        print(f"Found {len(existing)} existing test users.")

        created = []
        for i in range(count):
            username = f"loadtest_{i:04d}"
            if username in existing_usernames:
                continue

            user = User(
                username=username,
                email=f"{username}@loadtest.local",
                first_name=f"Load Test User {i}",
                last_name="",
                password_hash=get_password_hash(TEST_PASSWORD),
                role="user",
                is_active=True,
                is_verified=True,
                nuke_balance=5000,
            )
            db.add(user)
            created.append(username)

        await db.commit()
        return created


async def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-seed test users for load testing")
    parser.add_argument(
        "--users",
        type=int,
        default=100,
        help="Number of test users to create (default: 100)",
    )
    args = parser.parse_args()

    created = await create_test_users(args.users)
    print(f"Created {len(created)} new test users.")
    print(f"Credentials: username = loadtest_XXXX, password = {TEST_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
