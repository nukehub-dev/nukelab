# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Add toolchain fields to environment_templates

Revision ID: 0b7a7bf41017
Revises: 8298b4bb8ada
Create Date: 2026-08-14 09:33:54.744000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0b7a7bf41017"
down_revision: str | None = "8298b4bb8ada"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "environment_templates",
        sa.Column("tool_image", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "environment_templates",
        sa.Column("tool_mounts", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("environment_templates", "tool_mounts")
    op.drop_column("environment_templates", "tool_image")
