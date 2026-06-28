"""
PostgreSQL native partition management for time-series tables.

Tables managed:
  - activity_logs       (RANGE on created_at)
  - server_metrics      (RANGE on collected_at)
  - request_metrics     (RANGE on created_at)
  - credit_transactions (RANGE on created_at)

Usage:
  from app.db.partitioning import PartitionManager
  pm = PartitionManager(db_session)
  await pm.ensure_partitions("activity_logs", months_ahead=3)
  await pm.drop_old_partitions("activity_logs", months_to_keep=12)
"""

from datetime import UTC, datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy import text


class PartitionManager:
    """Manage PostgreSQL native range partitions for time-series tables."""

    PARTITION_CONFIG = {
        "activity_logs": {
            "column": "created_at",
            "granularity": "month",
        },
        "server_metrics": {
            "column": "collected_at",
            "granularity": "month",
        },
        "request_metrics": {
            "column": "created_at",
            "granularity": "month",
        },
        "credit_transactions": {
            "column": "created_at",
            "granularity": "month",
        },
    }

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _partition_name(table: str, year: int, month: int) -> str:
        return f"{table}_y{year}m{month:02d}"

    @staticmethod
    def _month_bounds(year: int, month: int) -> tuple[str, str]:
        start = datetime(year, month, 1)
        end = start + relativedelta(months=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    async def _partition_exists(self, table: str, partition_name: str) -> bool:
        result = await self.db.execute(
            text("SELECT 1 FROM pg_class WHERE relname = :name AND relkind = 'r'"),
            {"name": partition_name},
        )
        return result.scalar() is not None

    async def _ensure_default_partition(self, table: str) -> None:
        default_name = f"{table}_default"
        if await self._partition_exists(table, default_name):
            return
        await self.db.execute(
            text(f'CREATE TABLE IF NOT EXISTS "{default_name}" PARTITION OF "{table}" DEFAULT')
        )

    async def create_partition(self, table: str, year: int, month: int) -> str:
        """Create a monthly partition for the given table. Idempotent."""
        partition_name = self._partition_name(table, year, month)
        if await self._partition_exists(table, partition_name):
            return partition_name

        start, end = self._month_bounds(year, month)
        self.PARTITION_CONFIG[table]["column"]

        await self.db.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{partition_name}" '
                f"PARTITION OF \"{table}\" FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )
        return partition_name

    async def ensure_partitions(self, table: str, months_ahead: int = 3) -> list[str]:
        """
        Ensure partitions exist for the current month and N months ahead.
        Also creates a DEFAULT partition as a safety net.
        """
        if table not in self.PARTITION_CONFIG:
            raise ValueError(f"Unknown partitioned table: {table}")

        await self._ensure_default_partition(table)

        now = datetime.now(UTC)
        created = []
        for offset in range(months_ahead + 1):
            target = now + relativedelta(months=offset)
            name = await self.create_partition(table, target.year, target.month)
            created.append(name)
        return created

    async def drop_old_partitions(self, table: str, months_to_keep: int = 12) -> list[str]:
        """
        Detach and drop partitions older than N months.
        Returns the list of dropped partition names.
        """
        cutoff = datetime.now(UTC) - relativedelta(months=months_to_keep)
        cutoff_ym = cutoff.year * 12 + cutoff.month

        result = await self.db.execute(
            text(
                """
                SELECT inhrelid::regclass::text AS partition_name
                FROM pg_inherits
                JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
                WHERE parent.relname = :table
                  AND inhrelid::regclass::text NOT LIKE '%_default'
                ORDER BY inhrelid::regclass::text
                """
            ),
            {"table": table},
        )

        dropped = []
        for row in result.mappings().all():
            part_name = row["partition_name"]
            # Extract year/month from name like "activity_logs_y2024m01"
            try:
                suffix = part_name.split("_y")[1]  # "2024m01"
                year = int(suffix[:4])
                month = int(suffix[5:7])
                part_ym = year * 12 + month
                if part_ym < cutoff_ym:
                    await self.db.execute(
                        text(f'ALTER TABLE "{table}" DETACH PARTITION "{part_name}"')
                    )
                    await self.db.execute(text(f'DROP TABLE "{part_name}"'))
                    dropped.append(part_name)
            except (IndexError, ValueError):
                continue
        return dropped

    async def list_partitions(self, table: str) -> list[dict]:
        """List all partitions for a table with their row counts."""
        result = await self.db.execute(
            text(
                """
                SELECT
                    inhrelid::regclass::text AS partition_name,
                    pg_total_relation_size(inhrelid) AS total_bytes
                FROM pg_inherits
                JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
                WHERE parent.relname = :table
                ORDER BY inhrelid::regclass::text
                """
            ),
            {"table": table},
        )
        return [dict(row) for row in result.mappings().all()]
