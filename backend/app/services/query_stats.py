# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Query statistics and approximate count utilities.

Provides:
  - Approximate table counts via pg_class (fast, no table scan)
  - Top-N slow query reports from pg_stat_statements
  - EXPLAIN ANALYZE wrapper for ad-hoc profiling
"""

from typing import Any

from sqlalchemy import text


async def get_approximate_count(db, table_name: str) -> int:
    """
    Return an approximate row count for a table using pg_class.

    This is O(1) — it reads the planner's statistics instead of scanning.
    For unfiltered totals on large tables, use this instead of COUNT(*).
    """
    result = await db.execute(
        text(
            """
            SELECT reltuples::bigint AS approx_count
            FROM pg_class
            WHERE relname = :table
            """
        ),
        {"table": table_name},
    )
    row = result.mappings().first()
    return row["approx_count"] if row else 0


async def get_slow_queries(
    db,
    limit: int = 10,
    min_calls: int = 10,
) -> list[dict[str, Any]]:
    """
    Return the top-N most expensive queries by total execution time.

    Requires pg_stat_statements extension.
    """
    result = await db.execute(
        text(
            """
            SELECT
                queryid,
                LEFT(query, 120) AS query_preview,
                calls,
                ROUND(total_exec_time::numeric, 2) AS total_ms,
                ROUND(mean_exec_time::numeric, 4) AS mean_ms,
                rows,
                ROUND(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) AS cache_hit_pct
            FROM pg_stat_statements
            WHERE calls >= :min_calls
            ORDER BY total_exec_time DESC
            LIMIT :limit
            """
        ),
        {"limit": limit, "min_calls": min_calls},
    )
    return [dict(row) for row in result.mappings().all()]


async def get_table_sizes(db) -> list[dict[str, Any]]:
    """Return size and row estimates for all application tables."""
    result = await db.execute(
        text(
            """
            SELECT
                schemaname,
                relname AS table_name,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                pg_total_relation_size(relid) AS total_bytes,
                n_live_tup AS approx_rows
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(relid) DESC
            """
        )
    )
    return [dict(row) for row in result.mappings().all()]


async def explain_analyze(
    db,
    query: str,
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on a query.

    Returns the first plan node (root) as a dict.
    """
    explain_sql = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
    result = await db.execute(text(explain_sql), params or {})
    plans = result.scalar()
    if plans and len(plans) > 0:
        return plans[0]["Plan"]
    return {}
