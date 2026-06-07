#!/usr/bin/env python3
"""
Apply aggressive autovacuum settings to high-insert tables.

Run manually when `db_profiler.py autovacuum` shows dead_pct > 20%:

  python scripts/tune_autovacuum.py --dry-run
  python scripts/tune_autovacuum.py --apply

Tables tuned:
  - activity_logs
  - server_metrics
  - request_metrics
"""

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


TABLES = ["activity_logs", "server_metrics", "request_metrics"]

SETTINGS = {
    "autovacuum_vacuum_scale_factor": 0.05,
    "autovacuum_vacuum_threshold": 1000,
    "autovacuum_analyze_scale_factor": 0.02,
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply settings (default is dry-run)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        for table in TABLES:
            print(f"\nTable: {table}")
            for param, value in SETTINGS.items():
                sql = f'ALTER TABLE "{table}" SET ({param} = {value})'
                if args.apply:
                    await db.execute(text(sql))
                    print(f"  APPLIED: {param} = {value}")
                else:
                    print(f"  DRY-RUN: {sql}")
        if args.apply:
            await db.commit()
            print("\nCommit complete. Settings take effect immediately.")
        else:
            print("\nDry-run complete. Use --apply to execute.")


if __name__ == "__main__":
    asyncio.run(main())
