#!/usr/bin/env python3
"""
Database profiling and partition management CLI.

Run inside the backend container:
  python scripts/db_profiler.py slow-queries --limit 10
  python scripts/db_profiler.py table-sizes
  python scripts/db_profiler.py partitions --table activity_logs
  python scripts/db_profiler.py ensure-partitions --months-ahead 3
  python scripts/db_profiler.py drop-old --months-to-keep 12
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.services.query_stats import get_slow_queries, get_table_sizes, get_approximate_count
from app.db.partitioning import PartitionManager


async def cmd_slow_queries(args):
    async with AsyncSessionLocal() as db:
        queries = await get_slow_queries(db, limit=args.limit, min_calls=args.min_calls)
        if not queries:
            print("No pg_stat_statements data found (extension may be disabled or no queries captured yet).")
            return
        print(f"\n{'Query ID':>10} {'Calls':>8} {'Total ms':>12} {'Mean ms':>10} {'Rows':>8} {'Cache %':>8}  Preview")
        print("-" * 130)
        for q in queries:
            print(
                f"{q['queryid']:>10} {q['calls']:>8} {q['total_ms']:>12} {q['mean_ms']:>10} "
                f"{q['rows']:>8} {q['cache_hit_pct'] or 'N/A':>8}  {q['query_preview']}"
            )


async def cmd_table_sizes(args):
    async with AsyncSessionLocal() as db:
        tables = await get_table_sizes(db)
        print(f"\n{'Table':<40} {'Size':>12} {'Approx Rows':>12}")
        print("-" * 70)
        for t in tables:
            print(f"{t['table_name']:<40} {t['total_size']:>12} {t['approx_rows'] or 0:>12,}")


async def cmd_partitions(args):
    async with AsyncSessionLocal() as db:
        pm = PartitionManager(db)
        parts = await pm.list_partitions(args.table)
        print(f"\nPartitions for '{args.table}':")
        print(f"{'Partition Name':<50} {'Size (bytes)':>15}")
        print("-" * 70)
        for p in parts:
            print(f"{p['partition_name']:<50} {p['total_bytes']:>15,}")


async def cmd_ensure_partitions(args):
    async with AsyncSessionLocal() as db:
        pm = PartitionManager(db)
        tables = args.tables or list(pm.PARTITION_CONFIG.keys())
        for table in tables:
            created = await pm.ensure_partitions(table, months_ahead=args.months_ahead)
            print(f"{table}: ensured {len(created)} partition(s) — {', '.join(created)}")
            await db.commit()


async def cmd_drop_old(args):
    async with AsyncSessionLocal() as db:
        pm = PartitionManager(db)
        tables = args.tables or list(pm.PARTITION_CONFIG.keys())
        for table in tables:
            dropped = await pm.drop_old_partitions(table, months_to_keep=args.months_to_keep)
            print(f"{table}: dropped {len(dropped)} old partition(s)")
            if dropped:
                print("  " + "\n  ".join(dropped))
            await db.commit()


def main():
    parser = argparse.ArgumentParser(description="NukeLab DB profiler and partition manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_slow = sub.add_parser("slow-queries", help="Top slow queries from pg_stat_statements")
    p_slow.add_argument("--limit", type=int, default=10)
    p_slow.add_argument("--min-calls", type=int, default=10)

    sub.add_parser("table-sizes", help="Show table sizes and approximate row counts")

    p_parts = sub.add_parser("partitions", help="List partitions for a table")
    p_parts.add_argument("--table", required=True)

    p_ensure = sub.add_parser("ensure-partitions", help="Create upcoming monthly partitions")
    p_ensure.add_argument("--tables", nargs="+", help="Defaults to all partitioned tables")
    p_ensure.add_argument("--months-ahead", type=int, default=3)

    p_drop = sub.add_parser("drop-old", help="Drop partitions older than N months")
    p_drop.add_argument("--tables", nargs="+", help="Defaults to all partitioned tables")
    p_drop.add_argument("--months-to-keep", type=int, default=12)

    args = parser.parse_args()
    asyncio.run(globals()[f"cmd_{args.command.replace('-', '_')}"](args))


if __name__ == "__main__":
    main()
