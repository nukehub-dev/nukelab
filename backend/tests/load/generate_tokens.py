"""Pre-generate JWT tokens for load test users.

Runs inside the backend container to avoid login rate limits.
Tokens have a 2-hour expiry so endurance tests (30+ min) work cleanly.

Usage:
    docker compose exec backend python -m tests.load.generate_tokens
"""

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import select

from app.api.auth import create_access_token
from app.db.session import AsyncSessionLocal
from app.models.user import User

# Output path (relative to backend container working dir)
OUTPUT_PATH = Path("tests/load/tokens.json")
TOKEN_EXPIRY = timedelta(hours=2)


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username.like("loadtest_%")))
        users = result.scalars().all()

        if not users:
            print("No loadtest users found. Run setup_test_data first.")
            sys.exit(1)

        tokens = {}
        for u in users:
            token = create_access_token(
                data={"sub": u.username, "role": u.role},
                expires_delta=TOKEN_EXPIRY,
            )
            tokens[u.username] = token

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(tokens, indent=2))
        print(f"Generated {len(tokens)} tokens → {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
