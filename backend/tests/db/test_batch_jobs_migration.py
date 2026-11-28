# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Rehearse the additive batch job schema on a disposable PostgreSQL database."""

import asyncio
import uuid
from datetime import datetime

import asyncpg
import pytest
from alembic.script import ScriptDirectory

from alembic import command
from tests.db.test_launch_workflow_migration import connect
from tests.db.test_launch_workflow_migration import migration_database as migration_database

PREVIOUS_REVISION = "a4c9e2f7b1d3"
BATCH_REVISION = "b7d4e1c9a2f5"
ADMISSION_REVISION = "e2c7a9f4d6b1"
HEAD_REVISION = "a3b8c1d4e5f6"

REQUIRED_JOB_COLUMNS = {
    "user_id",
    "name",
    "idempotency_key_hash",
    "request_fingerprint",
    "revision_id",
    "plan_id",
    "volume_id",
    "argv",
    "max_runtime_seconds",
    "state",
    "reason_code",
    "state_changed_at",
    "queue_expires_at",
    "reserved_at",
    "create_requested_at",
    "start_requested_at",
    "start_observed_at",
    "deadline_at",
    "started_at",
    "finished_at",
    "stop_requested_at",
    "revision_snapshot",
    "plan_snapshot",
    "reservation_active",
    "volume_operation_id",
    "reserved_cpu",
    "reserved_memory_mib",
    "reserved_disk_mib",
    "volume_fencing_token",
    "cleanup_state",
    "cleanup_attempts",
    "last_cleanup_at",
    "container_id",
    "container_name",
    "runtime_identity",
    "executor_id",
    "heartbeat_at",
    "fencing_token",
    "exit_code",
    "outcome_code",
    "proof_class",
    "result_recorded_at",
    "log_state",
    "log_truncated",
    "log_size_bytes",
    "log_expires_at",
    "billing_mode",
    "charged_credits",
    "authorized_credits",
    "billing_rate_per_hour",
    "billing_state",
    "billing_transaction_id",
    "created_at",
    "updated_at",
}

REQUIRED_HOLD_COLUMNS = {
    "id",
    "user_id",
    "job_id",
    "amount",
    "state",
    "charged_credits",
    "unpaid_credits",
    "transaction_id",
    "created_at",
    "settled_at",
}


async def schema_state(database):
    connection = await connect(database)
    try:
        tables = set(
            await connection.fetchval(
                "SELECT array_agg(tablename) FROM pg_tables WHERE schemaname='public'"
            )
        )
        columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='batch_jobs'"
            )
        }
        log_columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='batch_job_logs'"
            )
        }
        hold_columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='credit_holds'"
            )
        }
        indexes = {
            row["indexname"]: row["indexdef"]
            for row in await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='batch_jobs'"
            )
        }
        volume_indexes = {
            row["indexname"]: row["indexdef"]
            for row in await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='volume_operations'"
            )
        }
        hold_indexes = {
            row["indexname"]: row["indexdef"]
            for row in await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='credit_holds'"
            )
        }
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        return {
            "tables": tables,
            "columns": columns,
            "log_columns": log_columns,
            "hold_columns": hold_columns,
            "indexes": indexes,
            "volume_indexes": volume_indexes,
            "hold_indexes": hold_indexes,
            "revision": revision,
        }
    finally:
        await connection.close()


async def seed_rows(database):
    connection = await connect(database)
    try:
        owner = uuid.uuid4()
        template = uuid.uuid4()
        revision = uuid.uuid4()
        job = uuid.uuid4()
        created = datetime(2026, 11, 27, 12)
        await connection.execute(
            "INSERT INTO users "
            "(id,username,email,role,profile_visibility,credit_requests_blocked) "
            "VALUES ($1,'batch-owner','batch-owner@example.test','user','private',false)",
            owner,
        )
        await connection.execute(
            "INSERT INTO environment_templates (id,name,slug,image) "
            "VALUES ($1,'Batch env','batch-env','batch:latest')",
            template,
        )
        await connection.execute(
            "INSERT INTO environment_revisions "
            "(id,template_id,fingerprint,template_fingerprint,configuration,"
            "runtime_identity,revoked,created_at) "
            "VALUES ($1,$2,$3,$4,'{}'::json,'{}'::json,false,$5)",
            revision,
            template,
            "a" * 64,
            "b" * 64,
            created,
        )
        await connection.execute(
            "INSERT INTO batch_jobs "
            "(id,user_id,name,idempotency_key_hash,request_fingerprint,revision_id,"
            "argv,max_runtime_seconds,state,state_changed_at,revision_snapshot,"
            "plan_snapshot,volume_snapshot,fencing_token,created_at,updated_at) "
            "VALUES ($1,$2,'migration job',$3,$4,$5,'[\"echo\"]'::jsonb,1800,'queued',"
            "$6,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$7,$6,$6)",
            job,
            owner,
            "c" * 64,
            "d" * 64,
            revision,
            created,
            uuid.uuid4(),
        )
        await connection.execute(
            "INSERT INTO batch_job_logs (job_id,text,captured_at) VALUES ($1,'hello',$2)",
            job,
            created,
        )
        hold = uuid.uuid4()
        await connection.execute(
            "INSERT INTO credit_holds (id,user_id,job_id,amount,created_at) "
            "VALUES ($1,$2,$3,$4,$5)",
            hold,
            owner,
            job,
            7,
            created,
        )
        row = await connection.fetchrow("SELECT * FROM batch_jobs WHERE id=$1", job)
        log = await connection.fetchrow("SELECT * FROM batch_job_logs WHERE job_id=$1", job)
        hold_row = await connection.fetchrow("SELECT * FROM credit_holds WHERE job_id=$1", job)
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await connection.execute(
                "INSERT INTO credit_holds (id,user_id,job_id,amount,created_at) "
                "VALUES ($1,$2,$3,$4,$5)",
                uuid.uuid4(),
                owner,
                job,
                7,
                created,
            )
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await connection.execute(
                "INSERT INTO batch_jobs "
                "(id,user_id,name,idempotency_key_hash,request_fingerprint,revision_id,"
                "argv,max_runtime_seconds,state,state_changed_at,revision_snapshot,"
                "plan_snapshot,volume_snapshot,fencing_token,created_at,updated_at) "
                "VALUES ($1,$2,'duplicate',$3,$4,$5,'[]'::jsonb,1800,'queued',"
                "$6,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$7,$6,$6)",
                uuid.uuid4(),
                owner,
                "c" * 64,
                "e" * 64,
                revision,
                created,
                uuid.uuid4(),
            )
        return row, log, hold_row
    finally:
        await connection.close()


def test_batch_job_migration_upgrade_downgrade_and_reupgrade(migration_database):
    config, database = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(BATCH_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(ADMISSION_REVISION).down_revision == BATCH_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == "f1a2b3c4d5e6"
    assert script.get_revision("f1a2b3c4d5e6").down_revision == ADMISSION_REVISION

    command.upgrade(config, "head")
    upgraded = asyncio.run(schema_state(database))
    assert upgraded["revision"] == HEAD_REVISION
    assert {"batch_jobs", "batch_job_logs", "credit_holds"} <= upgraded["tables"]
    assert REQUIRED_JOB_COLUMNS <= upgraded["columns"]
    assert upgraded["hold_columns"] == REQUIRED_HOLD_COLUMNS
    assert upgraded["log_columns"] == {
        "job_id",
        "text",
        "encoding",
        "truncated",
        "size_bytes",
        "captured_at",
        "expires_at",
    }
    idempotency = upgraded["indexes"]["uq_batch_jobs_owner_idempotency"]
    assert "UNIQUE INDEX" in idempotency
    assert "(user_id, idempotency_key_hash)" in idempotency
    history = upgraded["indexes"]["ix_batch_jobs_owner_history"]
    assert "(user_id, created_at, id)" in history
    pending = upgraded["indexes"]["ix_batch_jobs_pending_dispatch"]
    assert "(created_at, id)" in pending
    assert "queued" in pending
    assert "WHERE" in pending
    queued_expiry = upgraded["indexes"]["ix_batch_jobs_queued_expiry"]
    assert "(queue_expires_at, id)" in queued_expiry
    assert "queued" in queued_expiry
    recovery = upgraded["indexes"]["ix_batch_jobs_active_recovery"]
    assert "(state, heartbeat_at, id)" in recovery
    for state in ("starting", "running", "cancelling", "recovery_required"):
        assert state in recovery
    reservations = upgraded["indexes"]["ix_batch_jobs_unreleased_reservations"]
    assert "(reserved_at, id)" in reservations
    assert "reservation_active = true" in reservations
    exclusive = upgraded["volume_indexes"]["uq_volume_operations_exclusive"]
    assert "UNIQUE INDEX" in exclusive
    assert "job_writer" in exclusive
    assert "backup" in exclusive and "restore" in exclusive
    hold_user = upgraded["hold_indexes"]["ix_credit_holds_user_state"]
    assert "(user_id, state)" in hold_user
    hold_job = upgraded["hold_indexes"]["uq_credit_holds_job_id"]
    assert "UNIQUE INDEX" in hold_job
    assert "(job_id)" in hold_job

    row, log, hold = asyncio.run(seed_rows(database))
    assert row["state"] == "queued"
    assert row["billing_mode"] == "zero_cost"
    assert row["charged_credits"] == 0
    assert row["authorized_credits"] == 0
    assert row["billing_rate_per_hour"] == 0
    assert row["billing_state"] == "none"
    assert row["reservation_active"] is False
    assert row["log_state"] == "pending"
    assert row["log_truncated"] is False
    assert row["log_size_bytes"] == 0
    assert log["encoding"] == "utf-8"
    assert log["truncated"] is False
    assert log["size_bytes"] == 0
    assert hold["amount"] == 7
    assert hold["state"] == "held"
    assert hold["charged_credits"] == 0
    assert hold["unpaid_credits"] == 0
    assert hold["transaction_id"] is None
    assert hold["settled_at"] is None

    command.downgrade(config, ADMISSION_REVISION)
    downgraded = asyncio.run(schema_state(database))
    assert downgraded["revision"] == ADMISSION_REVISION
    assert "credit_holds" not in downgraded["tables"]
    assert downgraded["hold_columns"] == set()
    assert {
        "authorized_credits",
        "billing_rate_per_hour",
        "billing_state",
    }.isdisjoint(downgraded["columns"])
    assert {
        "reserved_cpu",
        "reserved_memory_mib",
        "reserved_disk_mib",
        "volume_fencing_token",
        "cleanup_state",
        "cleanup_attempts",
        "last_cleanup_at",
    } <= downgraded["columns"]

    command.downgrade(config, BATCH_REVISION)
    downgraded = asyncio.run(schema_state(database))
    assert downgraded["revision"] == BATCH_REVISION
    assert {"batch_jobs", "batch_job_logs"} <= downgraded["tables"]
    assert {
        "reserved_cpu",
        "reserved_memory_mib",
        "reserved_disk_mib",
        "volume_fencing_token",
        "cleanup_state",
        "cleanup_attempts",
        "last_cleanup_at",
    }.isdisjoint(downgraded["columns"])
    old_exclusive = downgraded["volume_indexes"]["uq_volume_operations_exclusive"]
    assert "job_writer" not in old_exclusive

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = asyncio.run(schema_state(database))
    assert downgraded["revision"] == PREVIOUS_REVISION
    assert downgraded["tables"].isdisjoint({"batch_jobs", "batch_job_logs", "credit_holds"})
    assert downgraded["columns"] == set()
    assert downgraded["log_columns"] == set()
    assert downgraded["hold_columns"] == set()

    command.upgrade(config, "head")
    reupgraded = asyncio.run(schema_state(database))
    assert reupgraded["revision"] == HEAD_REVISION
    assert {"batch_jobs", "batch_job_logs", "credit_holds"} <= reupgraded["tables"]
    assert REQUIRED_JOB_COLUMNS <= reupgraded["columns"]
    assert reupgraded["hold_columns"] == REQUIRED_HOLD_COLUMNS
