# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""baseline

Revision ID: 281a4c5d5529
Revises:
Create Date: 2026-06-07 08:15:00.000000

"""
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from alembic import op
import sqlalchemy as sa

from app.db.base import Base

# Import all models to register them with Base.metadata
from app.models.user import User  # noqa: F401
from app.models.server import Server  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.api_token import ApiToken  # noqa: F401
from app.models.credit_transaction import CreditTransaction  # noqa: F401
from app.models.activity_log import ActivityLog  # noqa: F401
from app.models.environment_template import EnvironmentTemplate  # noqa: F401
from app.models.server_plan import ServerPlan  # noqa: F401
from app.models.resource_quota import ResourceQuota  # noqa: F401
from app.models.server_queue import ServerQueue  # noqa: F401
from app.models.alert_rule import AlertRule  # noqa: F401
from app.models.alert_history import AlertHistory  # noqa: F401
from app.models.health_check import HealthCheck  # noqa: F401
from app.models.server_metric import ServerMetric  # noqa: F401
from app.models.system_metric import SystemMetric  # noqa: F401
from app.models.volume import Volume  # noqa: F401
from app.models.volume_backup import VolumeBackup  # noqa: F401
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember  # noqa: F401
from app.models.workspace_volume import WorkspaceVolume  # noqa: F401
from app.models.workspace_invitation import WorkspaceInvitation  # noqa: F401
from app.models.server_access_token import ServerAccessToken  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.plan_access import UserPlanAccess, WorkspacePlanAccess  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
from app.models.daily_server_metric import DailyServerMetric  # noqa: F401
from app.models.login_event import LoginEvent  # noqa: F401


# revision identifiers, used by Alembic.
revision = '281a4c5d5529'
down_revision = None
branch_labels = None
depends_on = None


_PARTITIONED_TABLES = {
    "activity_logs": "created_at",
    "server_metrics": "collected_at",
    "request_metrics": "created_at",
    "credit_transactions": "created_at",
}


def _partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_y{year}m{month:02d}"


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = datetime(year, month, 1)
    end = start + relativedelta(months=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _create_partitions() -> None:
    """Create DEFAULT + current-month partitions for time-series tables."""
    now = datetime.now(timezone.utc)
    for table, column in _PARTITIONED_TABLES.items():
        # DEFAULT partition catches anything outside explicit partitions
        op.execute(
            sa.text(f'CREATE TABLE IF NOT EXISTS "{table}_default" PARTITION OF "{table}" DEFAULT')
        )
        # Current month
        start, end = _month_bounds(now.year, now.month)
        name = _partition_name(table, now.year, now.month)
        op.execute(
            sa.text(
                f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF "{table}" '
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )


def upgrade() -> None:
    # PostgreSQL extension for query observability
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))

    # Create all tables from SQLAlchemy models
    Base.metadata.create_all(bind=op.get_bind())

    # Create initial partitions for time-series tables
    _create_partitions()


def downgrade() -> None:
    # Drop all tables (reverse dependency order)
    Base.metadata.drop_all(bind=op.get_bind())

    # Drop extension
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_stat_statements"))
