"""Tests for PostgreSQL native partition management."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest import mock
from sqlalchemy import text

from app.db.partitioning import PartitionManager


class TestPartitionManagerStaticMethods:
    """Tests for static helpers."""

    def test_partition_name(self):
        assert (
            PartitionManager._partition_name("activity_logs", 2024, 1) == "activity_logs_y2024m01"
        )
        assert (
            PartitionManager._partition_name("activity_logs", 2024, 12) == "activity_logs_y2024m12"
        )

    def test_month_bounds(self):
        start, end = PartitionManager._month_bounds(2024, 1)
        assert start == "2024-01-01"
        assert end == "2024-02-01"

        start, end = PartitionManager._month_bounds(2024, 12)
        assert start == "2024-12-01"
        assert end == "2025-01-01"


@pytest_asyncio.fixture
async def partition_table(db_session):
    """Create and yield a partitioned test table, then clean up."""
    table_name = "test_partitioned"
    await db_session.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
    await db_session.execute(
        text(
            f"""
            CREATE TABLE "{table_name}" (
                id serial,
                created_at timestamp NOT NULL,
                data text
            ) PARTITION BY RANGE (created_at)
            """
        )
    )
    yield table_name
    await db_session.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


class TestPartitionManagerWithDB:
    """Tests requiring a real PostgreSQL database."""

    @pytest.mark.asyncio
    async def test_ensure_partitions_creates_partitions(self, db_session, partition_table):
        pm = PartitionManager(db_session)
        with mock.patch.object(
            PartitionManager,
            "PARTITION_CONFIG",
            {partition_table: {"column": "created_at", "granularity": "month"}},
        ):
            created = await pm.ensure_partitions(partition_table, months_ahead=2)

        assert len(created) == 3  # current month + 2 ahead
        # Verify default partition was created
        result = await db_session.execute(
            text("SELECT 1 FROM pg_class WHERE relname = :name AND relkind = 'r'"),
            {"name": f"{partition_table}_default"},
        )
        assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_ensure_partitions_idempotent(self, db_session, partition_table):
        pm = PartitionManager(db_session)
        with mock.patch.object(
            PartitionManager,
            "PARTITION_CONFIG",
            {partition_table: {"column": "created_at", "granularity": "month"}},
        ):
            first = await pm.ensure_partitions(partition_table, months_ahead=1)
            second = await pm.ensure_partitions(partition_table, months_ahead=1)
            assert first == second

    @pytest.mark.asyncio
    async def test_ensure_partitions_unknown_table(self, db_session):
        pm = PartitionManager(db_session)
        with pytest.raises(ValueError, match="Unknown partitioned table"):
            await pm.ensure_partitions("nonexistent", months_ahead=1)

    @pytest.mark.asyncio
    async def test_list_partitions(self, db_session, partition_table):
        pm = PartitionManager(db_session)
        with mock.patch.object(
            PartitionManager,
            "PARTITION_CONFIG",
            {partition_table: {"column": "created_at", "granularity": "month"}},
        ):
            await pm.ensure_partitions(partition_table, months_ahead=1)
            partitions = await pm.list_partitions(partition_table)
            assert len(partitions) >= 2  # month partitions + default
            for p in partitions:
                assert "partition_name" in p
                assert "total_bytes" in p

    @pytest.mark.asyncio
    async def test_drop_old_partitions(self, db_session, partition_table):
        pm = PartitionManager(db_session)
        with mock.patch.object(
            PartitionManager,
            "PARTITION_CONFIG",
            {partition_table: {"column": "created_at", "granularity": "month"}},
        ):
            now = datetime.now(timezone.utc)
            # Create a partition for 2 years ago (should be dropped)
            old_year = now.year - 2
            await pm.create_partition(partition_table, old_year, now.month)

            # Create a partition for next year (should NOT be dropped)
            future_year = now.year + 1
            await pm.create_partition(partition_table, future_year, now.month)

            dropped = await pm.drop_old_partitions(partition_table, months_to_keep=6)
            assert any(str(old_year) in d for d in dropped)
            assert not any(str(future_year) in d for d in dropped)

    @pytest.mark.asyncio
    async def test_create_partition(self, db_session, partition_table):
        pm = PartitionManager(db_session)
        with mock.patch.object(
            PartitionManager,
            "PARTITION_CONFIG",
            {partition_table: {"column": "created_at", "granularity": "month"}},
        ):
            name = await pm.create_partition(partition_table, 2030, 6)
            assert name == f"{partition_table}_y2030m06"
            # Idempotent second call
            name2 = await pm.create_partition(partition_table, 2030, 6)
            assert name2 == name
