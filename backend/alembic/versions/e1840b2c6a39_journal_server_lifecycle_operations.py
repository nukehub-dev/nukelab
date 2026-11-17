"""journal server lifecycle operations

Revision ID: e1840b2c6a39
Revises: d731a8f4c092
Create Date: 2026-11-16 14:36:02.742681

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "e1840b2c6a39"
down_revision = "d731a8f4c092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    _preflight(connection)
    inspector = sa.inspect(connection)
    if "server_launch_operations" not in inspector.get_table_names():
        _create_operations()
    indexes = {
        row["name"] for row in sa.inspect(connection).get_indexes("server_launch_operations")
    }
    if "ix_server_launch_operations_server_id" not in indexes:
        op.create_index(
            "ix_server_launch_operations_server_id", "server_launch_operations", ["server_id"]
        )
    if "uq_server_launch_operations_active" not in indexes:
        op.create_index(
            "uq_server_launch_operations_active",
            "server_launch_operations",
            ["server_id"],
            unique=True,
            postgresql_where=sa.text("state IN ('prepared', 'executing', 'uncertain')"),
        )
    queue_indexes = {row["name"] for row in sa.inspect(connection).get_indexes("server_queue")}
    if "uq_server_queue_active_owner_name" not in queue_indexes:
        op.create_index(
            "uq_server_queue_active_owner_name",
            "server_queue",
            ["user_id", "server_name"],
            unique=True,
            postgresql_where=sa.text("status IN ('pending', 'starting')"),
        )
    constraints = {row["name"] for row in sa.inspect(connection).get_unique_constraints("servers")}
    if "uq_servers_owner_name" not in constraints:
        op.create_unique_constraint("uq_servers_owner_name", "servers", ["user_id", "name"])
    _backfill(connection)


def _preflight(connection):
    if connection.scalar(
        sa.text("SELECT count(*) FROM server_queue WHERE status='starting' AND server_id IS NULL")
    ):
        raise RuntimeError("Reconcile legacy starting queue requests before upgrading")
    connection.execute(
        sa.text(
            "UPDATE server_queue SET status='cancelled', reason_code='configuration_changed', "
            "error_message='Original launch configuration is unavailable. Submit a new request.' "
            "WHERE status='pending' AND (request_version IS NULL OR request_payload IS NULL)"
        )
    )
    checks = (
        "SELECT count(*) FROM (SELECT user_id,name FROM servers GROUP BY user_id,name HAVING count(*)>1) conflicts",
        "SELECT count(*) FROM (SELECT user_id,server_name FROM server_queue WHERE status IN ('pending','starting') "
        "GROUP BY user_id,server_name HAVING count(*)>1) conflicts",
        "SELECT count(*) FROM server_queue q JOIN servers s ON s.user_id=q.user_id AND s.name=q.server_name "
        "WHERE q.status IN ('pending','starting') AND q.server_id IS DISTINCT FROM s.id",
    )
    if any(connection.scalar(sa.text(query)) for query in checks):
        raise RuntimeError(
            "Resolve conflicting server/queue names before upgrading; no user records were deleted"
        )


def _backfill(connection):
    import uuid

    rows = (
        connection.execute(
            sa.text(
                "SELECT i.*, s.allocated_cpu, s.allocated_memory, s.allocated_disk, "
                "s.allocated_gpu, s.status AS server_status, s.container_id, r.id AS recorded_launch "
                "FROM server_launch_intents i JOIN servers s ON s.id=i.server_id "
                "LEFT JOIN server_launch_records r ON r.id=i.server_id AND r.server_id=i.server_id AND r.user_id=i.owner_id AND r.revision_id=i.revision_id AND r.generation=1 "
                "WHERE NOT EXISTS (SELECT 1 FROM server_launch_operations o WHERE o.id=i.server_id)"
            )
        )
        .mappings()
        .all()
    )
    insert = sa.text(
        "INSERT INTO server_launch_operations "
        "(id,server_id,owner_id,action,state,fencing_token,revision_id,request_payload,mounts,previous_mounts,gpu_devices,"
        "username,environment_slug,resources,generation,previous_container_id,previous_status,reason_code,created_at,updated_at,finished_at) "
        "VALUES (:id,:id,:owner_id,'create',:state,:token,:revision_id,:payload,:mounts,:previous,:devices,:username,:slug,"
        ":resources,1,NULL,:status,:reason,:created,:created,:finished)"
    ).bindparams(
        sa.bindparam("payload", type_=postgresql.JSONB),
        sa.bindparam("mounts", type_=postgresql.JSONB),
        sa.bindparam("previous", type_=postgresql.JSONB),
        sa.bindparam("devices", type_=postgresql.JSONB),
        sa.bindparam("resources", type_=postgresql.JSONB),
    )
    for row in rows:
        if any(
            row[key] is None
            for key in ("allocated_cpu", "allocated_memory", "allocated_disk", "allocated_gpu")
        ):
            raise RuntimeError("Reconcile incomplete launch resource reservations before upgrading")
        complete = row["recorded_launch"] is not None and row["server_status"] in (
            "running",
            "stopped",
        )
        connection.execute(
            insert,
            {
                "id": row["server_id"],
                "owner_id": row["owner_id"],
                "state": "succeeded" if complete else "uncertain",
                "token": uuid.uuid4(),
                "revision_id": row["revision_id"],
                "payload": row["request_payload"],
                "mounts": row["mounts"],
                "previous": [],
                "devices": row["gpu_devices"],
                "username": row["username"],
                "slug": row["environment_slug"],
                "resources": {
                    "cpu": row["allocated_cpu"],
                    "memory": row["allocated_memory"],
                    "disk": row["allocated_disk"],
                    "gpu": row["allocated_gpu"],
                },
                "status": row["server_status"],
                "reason": None if complete else "recovery_required",
                "created": row["created_at"],
                "finished": row["created_at"] if complete else None,
            },
        )
        if not complete:
            connection.execute(
                sa.text(
                    "UPDATE servers SET status='starting',status_reason='recovery_required' WHERE id=:id"
                ),
                {"id": row["server_id"]},
            )


def _create_operations():
    op.create_table(
        "server_launch_operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("fencing_token", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mounts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("previous_mounts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gpu_devices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("environment_slug", sa.String(length=255), nullable=True),
        sa.Column("resources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("previous_container_id", sa.String(length=255), nullable=True),
        sa.Column("previous_status", sa.String(length=50), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["environment_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_constraint("uq_servers_owner_name", "servers", type_="unique")
    op.drop_index(
        "uq_server_queue_active_owner_name",
        table_name="server_queue",
        postgresql_where=sa.text("status IN ('pending', 'starting')"),
    )
    op.drop_index(
        "uq_server_launch_operations_active",
        table_name="server_launch_operations",
        postgresql_where=sa.text("state IN ('prepared', 'executing', 'uncertain')"),
    )
    op.drop_index(
        op.f("ix_server_launch_operations_server_id"), table_name="server_launch_operations"
    )
    op.drop_table("server_launch_operations")
