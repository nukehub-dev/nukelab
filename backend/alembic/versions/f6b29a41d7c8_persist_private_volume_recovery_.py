"""persist private volume recovery operations

Revision ID: f6b29a41d7c8
Revises: e1840b2c6a39
Create Date: 2026-11-17 18:07:04.848836

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "f6b29a41d7c8"
down_revision = "e1840b2c6a39"
branch_labels = None
depends_on = None


def _add_column(table, column):
    if column.name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("volume_restores"):
        op.create_table(
            "volume_restores",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("backup_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=True),
            sa.Column("destination_volume_id", sa.UUID(), nullable=True),
            sa.Column("destination_name", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("max_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column(
                "reserved_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False
            ),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("fencing_token", sa.UUID(), nullable=False),
            sa.Column("helper_identity", sa.String(length=255), nullable=True),
            sa.Column("reason_code", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["backup_id"], ["volume_backups.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["destination_volume_id"], ["volumes.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_volume_restores_backup_id"), "volume_restores", ["backup_id"], unique=False
        )
        op.create_index(
            op.f("ix_volume_restores_destination_volume_id"),
            "volume_restores",
            ["destination_volume_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_volume_restores_user_id"), "volume_restores", ["user_id"], unique=False
        )
    _add_column("volume_backups", sa.Column("source_volume_id", sa.UUID(), nullable=True))
    _add_column(
        "volume_backups", sa.Column("source_display_name", sa.String(length=255), nullable=True)
    )
    _add_column(
        "volume_backups",
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _add_column("volume_backups", sa.Column("format_version", sa.String(length=50), nullable=True))
    _add_column("volume_backups", sa.Column("sha256", sa.String(length=64), nullable=True))
    _add_column("volume_backups", sa.Column("logical_bytes", sa.BigInteger(), nullable=True))
    _add_column("volume_backups", sa.Column("member_count", sa.Integer(), nullable=True))
    _add_column("volume_backups", sa.Column("max_logical_bytes", sa.BigInteger(), nullable=True))
    _add_column(
        "volume_backups",
        sa.Column("reserved_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    _add_column("volume_backups", sa.Column("fencing_token", sa.UUID(), nullable=True))
    _add_column(
        "volume_backups", sa.Column("helper_identity", sa.String(length=255), nullable=True)
    )
    _add_column("volume_backups", sa.Column("reason_code", sa.String(length=50), nullable=True))
    _add_column("volume_backups", sa.Column("expires_at", sa.DateTime(), nullable=True))
    if not any(
        index["name"] == "ix_volume_backups_source_volume_id"
        for index in sa.inspect(op.get_bind()).get_indexes("volume_backups")
    ):
        op.create_index(
            "ix_volume_backups_source_volume_id",
            "volume_backups",
            ["source_volume_id"],
            unique=False,
        )
    if not any(
        fk["constrained_columns"] == ["source_volume_id"]
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("volume_backups")
    ):
        op.create_foreign_key(
            "fk_volume_backups_source_volume",
            "volume_backups",
            "volumes",
            ["source_volume_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys("volume_backups"):
        if fk["constrained_columns"] == ["source_volume_id"]:
            op.drop_constraint(fk["name"], "volume_backups", type_="foreignkey")
    op.drop_index(op.f("ix_volume_backups_source_volume_id"), table_name="volume_backups")
    op.drop_column("volume_backups", "expires_at")
    op.drop_column("volume_backups", "reason_code")
    op.drop_column("volume_backups", "helper_identity")
    op.drop_column("volume_backups", "fencing_token")
    op.drop_column("volume_backups", "reserved_bytes")
    op.drop_column("volume_backups", "max_logical_bytes")
    op.drop_column("volume_backups", "member_count")
    op.drop_column("volume_backups", "logical_bytes")
    op.drop_column("volume_backups", "sha256")
    op.drop_column("volume_backups", "format_version")
    op.drop_column("volume_backups", "source_metadata")
    op.drop_column("volume_backups", "source_display_name")
    op.drop_column("volume_backups", "source_volume_id")
    op.drop_index(op.f("ix_volume_restores_user_id"), table_name="volume_restores")
    op.drop_index(op.f("ix_volume_restores_destination_volume_id"), table_name="volume_restores")
    op.drop_index(op.f("ix_volume_restores_backup_id"), table_name="volume_restores")
    op.drop_table("volume_restores")
