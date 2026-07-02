# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Default retention policies for data lifecycle management."""

DEFAULT_RETENTION_POLICIES = {
    "metrics_retention_days": 30,
    "system_metrics_retention_days": 90,
    "health_check_retention_days": 30,
    "alert_history_retention_days": 90,
    "activity_log_retention_days": 365,
    "notification_retention_days": 30,
    "daily_rollup_retention_days": 730,
    "cleanup_enabled": True,
    "cleanup_run_hour": 4,
}

VALIDATION_RANGES = {
    "metrics_retention_days": (7, 365),
    "system_metrics_retention_days": (7, 730),
    "health_check_retention_days": (7, 365),
    "alert_history_retention_days": (7, 730),
    "activity_log_retention_days": (30, 1825),
    "notification_retention_days": (7, 365),
    "daily_rollup_retention_days": (30, 1825),
    "cleanup_run_hour": (0, 23),
}
