# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only storage enforcement capability for the batch-job pilot.

The configured per-volume size limit is only a real enforcement boundary when
the host filesystem applies it in the kernel (XFS project quota for the volume
storage path). This module answers that question without mutating storage and
without exposing host paths to API clients.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.core.logging import get_logger
from app.services.xfs_quota_service import xfs_quota_service

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StorageLimitCapability:
    """One probe result plus the operator's enforcement policy."""

    enforced: bool
    required: bool
    reason_code: str | None = None


class StorageCapabilityService:
    """Probe kernel enforcement truthfully; never advertise an unenforced limit."""

    @staticmethod
    def probe() -> StorageLimitCapability:
        """Read-only capability check for the configured volume storage path."""
        required = bool(settings.batch_jobs_require_storage_enforcement)
        try:
            result = xfs_quota_service.probe_configured_storage()
        except Exception as exc:
            # A broken probe is not evidence of enforcement. Fail closed with a
            # stable reason instead of turning a capabilities read into a 500.
            logger.warning(
                "Storage enforcement probe failed",
                extra={"error_class": type(exc).__name__},
            )
            return StorageLimitCapability(
                enforced=False,
                required=required,
                reason_code="storage_probe_failed",
            )
        return StorageLimitCapability(
            enforced=result.available,
            required=required,
            reason_code=None if result.available else result.reason,
        )


__all__ = ["StorageCapabilityService", "StorageLimitCapability"]
