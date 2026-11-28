#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Seed the disposable batch-job CI fixture inside the backend container.

Run this only against a disposable stack where the local ``nukelab-e2e-runtime:a``
image already exists. It creates or reuses:

* an active zero-cost CPU plan (``jobs-e2e-cpu``);
* a filler plan sized to the configured global resource pool, used by the real
  browser scenario to occupy the last slot (``jobs-e2e-filler``);
* an active, public environment template backed by the fixture image;
* an approved local-identity ``EnvironmentRevision`` so job admission can prove
  the image by Docker local ID without a registry.

Example (from the repository root):

    docker exec -i \
      -e NUKELAB_JOBS_SEED_ALLOW=1 \
      -e TEST_ADMIN_USERNAME=admin \
      -e E2E_RUNTIME_IMAGE=nukelab-e2e-runtime:a \
      nukelab-backend python - < scripts/ci/seed-jobs-fixture.py

The script is idempotent. It prints one bounded JSON object on success and exits
non-zero on an unsafe environment or a fixture mismatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

JOBS_PLAN_SLUG = "jobs-e2e-cpu"
FILLER_PLAN_SLUG = "jobs-e2e-filler"
ENVIRONMENT_SLUG = "jobs-e2e-runtime"
ENVIRONMENT_NAME = "Jobs E2E Approved Runtime"
DEFAULT_RUNTIME_IMAGE = "nukelab-e2e-runtime:a"
JOB_PLAN_CPU = 1.0
JOB_PLAN_MEMORY_MIB = 1024
JOB_PLAN_DISK_MIB = 1024
FILLER_DISK_MIB = 10 * 1024


class SeedError(RuntimeError):
    """A bounded, operator-readable fixture error."""


def _require_disposable() -> None:
    if os.environ.get("NUKELAB_JOBS_SEED_ALLOW") != "1":
        raise SeedError(
            "Refusing to seed without NUKELAB_JOBS_SEED_ALLOW=1; "
            "this fixture is for disposable stacks only"
        )


async def _seed() -> dict[str, object]:
    from app.config import settings
    from app.container.factory import get_fresh_driver
    from app.db.session import AsyncSessionLocal
    from app.models.environment_template import EnvironmentTemplate
    from app.models.server_plan import ServerPlan
    from app.models.user import User
    from app.schemas.environment_manifest import ImageIdentity
    from app.services.environment_revision_service import (
        EnvironmentRevisionService,
        fingerprint,
        template_configuration,
    )
    from sqlalchemy import select

    if not settings.batch_jobs_submission_enabled:
        raise SeedError(
            "BATCH_JOBS_SUBMISSION_ENABLED must be true on the disposable stack before seeding"
        )

    runtime_image = os.environ.get("E2E_RUNTIME_IMAGE", DEFAULT_RUNTIME_IMAGE)
    admin_username = os.environ.get("TEST_ADMIN_USERNAME", "admin")
    pool_cpu = float(settings.resource_pool_cpu)
    pool_memory_mib = int(settings.resource_pool_memory_mib)
    pool_disk_mib = int(settings.resource_pool_disk_mib)
    if pool_cpu < JOB_PLAN_CPU or pool_memory_mib < JOB_PLAN_MEMORY_MIB:
        raise SeedError("resource pool is smaller than the zero-cost CPU job plan")
    if pool_disk_mib < JOB_PLAN_DISK_MIB:
        raise SeedError("resource pool disk is smaller than the zero-cost CPU job plan")

    filler_disk_mib = min(pool_disk_mib, FILLER_DISK_MIB)

    driver = await get_fresh_driver()
    try:
        try:
            raw_identity = await driver.resolve_image(runtime_image)
        except Exception as exc:
            raise SeedError(
                f"fixture image {runtime_image!r} is not available to the backend runtime: "
                f"{type(exc).__name__}"
            ) from exc
        runtime = ImageIdentity.model_validate(raw_identity)

        async with AsyncSessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == admin_username))
            if admin is None:
                raise SeedError(f"admin user {admin_username!r} does not exist")

            plan = await db.scalar(
                select(ServerPlan).where(ServerPlan.slug == JOBS_PLAN_SLUG)
            )
            if plan is None:
                plan = ServerPlan(slug=JOBS_PLAN_SLUG)
                db.add(plan)
            plan.name = "Jobs E2E CPU"
            plan.description = (
                "Disposable zero-cost CPU plan for the batch-job browser scenario."
            )
            plan.category = "cpu"
            plan.cpu_limit = JOB_PLAN_CPU
            plan.memory_limit = f"{JOB_PLAN_MEMORY_MIB}m"
            plan.disk_limit = f"{JOB_PLAN_DISK_MIB}m"
            plan.gpu_limit = 0
            plan.max_servers_per_user = 5
            plan.cost_per_hour = 0
            plan.cooldown_seconds = 0
            plan.allow_scheduling = True
            plan.allow_snapshots = False
            plan.is_public = True
            plan.visible_to_roles = []
            plan.is_active = True
            plan.priority = 0

            filler = await db.scalar(
                select(ServerPlan).where(ServerPlan.slug == FILLER_PLAN_SLUG)
            )
            if filler is None:
                filler = ServerPlan(slug=FILLER_PLAN_SLUG)
                db.add(filler)
            filler.name = "Jobs E2E Capacity Filler"
            filler.description = (
                "Disposable interactive plan sized to the configured resource pool; "
                "occupies the last job slot in the batch-job browser scenario."
            )
            filler.category = "cpu"
            filler.cpu_limit = pool_cpu
            filler.memory_limit = f"{pool_memory_mib}m"
            filler.disk_limit = f"{filler_disk_mib}m"
            filler.gpu_limit = 0
            filler.max_servers_per_user = 5
            filler.cost_per_hour = 0
            filler.cooldown_seconds = 0
            filler.allow_scheduling = True
            filler.allow_snapshots = False
            filler.is_public = True
            filler.visible_to_roles = []
            filler.is_active = True
            filler.priority = 0

            template = await db.scalar(
                select(EnvironmentTemplate).where(
                    EnvironmentTemplate.slug == ENVIRONMENT_SLUG
                )
            )
            if template is None:
                template = EnvironmentTemplate(slug=ENVIRONMENT_SLUG)
                db.add(template)
            template.name = ENVIRONMENT_NAME
            template.image = runtime_image
            template.description = (
                "Disposable approved runtime for the real batch-job browser scenario."
            )
            template.category = "base"
            template.is_active = True
            template.is_public = True
            template.tool_image = None
            template.tool_mounts = []
            template.environment_variables = {}
            template.packages = []
            template.volumes = []
            template.ports = []
            if template.created_by is None:
                template.created_by = admin.id
            await db.flush()

            async def authorize_template(_template: EnvironmentTemplate) -> None:
                return None

            revision_service = EnvironmentRevisionService(db, authorize_template)
            configuration = template_configuration(template)
            revision = await revision_service.capture(
                template.id,
                expected_template_fingerprint=fingerprint(configuration),
                runtime=runtime,
                allow_reapproval=True,
            )
            await db.commit()

            return {
                "ok": True,
                "plan_slug": JOBS_PLAN_SLUG,
                "plan_id": str(plan.id),
                "filler_plan_slug": FILLER_PLAN_SLUG,
                "filler_plan_id": str(filler.id),
                "environment_slug": ENVIRONMENT_SLUG,
                "environment_name": ENVIRONMENT_NAME,
                "environment_id": str(template.id),
                "revision_id": str(revision.id),
                "revision_fingerprint": revision.fingerprint,
                "runtime_image": runtime_image,
                "runtime_local_id": runtime.local_id,
                "pool": {
                    "cpu": pool_cpu,
                    "memory_mib": pool_memory_mib,
                    "disk_mib": pool_disk_mib,
                },
            }
    finally:
        await driver.close()


def main() -> int:
    # Keep stdout reserved for the single result JSON consumed by CI.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        _require_disposable()
        result = asyncio.run(_seed())
    except SeedError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - bounded CI diagnostic
        print(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
