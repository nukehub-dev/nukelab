# NukeLab Roadmap

**Current baseline** is `v2.3.0`. Users can queue server launches, recreate approved environments, and recover private volumes offline. The platform can reconcile interrupted operations and match registry-verified environments across installations. The 2.4.0 single-run batch-job work is implemented but is not released.

## Product priorities

| Work | Status | Next outcome |
| --- | --- | --- |
| Scientific batch jobs | Partial | Owner Jobs surface, durable zero-cost and paid admission with a `job_writer` volume guard, hold-based credit settlement/refunds, hardened no-network runtime with `/work` preparation, bounded monitor/cleanup/recovery, jobs-specific cross-owner permissions with reason-audited safe cancellation and proof-only admin reconcile, bounded physical log purge, owner completion notifications, truthful storage-enforcement capability reporting, and guided first launch are implemented. Backend full suite (5,141 passed, 6 skipped, 0 failed), frontend suites, mocked owner/admin browser suites, a real API→PostgreSQL/Redis/Celery/Docker zero-cost job, a real paid hold/settlement job, and worker/broker interruption drills passed on a disposable Docker stack. Remaining gates: run the explicit CI browser job on a remote runner, prove the over-cap write on XFS project-quota storage, exercise reserve-before-create interruption variants, complete staging upgrade/rollback/off-host restore and `preload_only` rehearsal, Podman enablement, and scoped secrets. Paid remains gated by `BATCH_JOBS_ALLOW_PAID_PLANS` and plan visibility. [Batch jobs](../architecture/BATCH-JOBS.md) |
| Scoped workload secrets | Deferred | Not implemented. Define credential ownership, authorized injection, rotation, and redaction before workloads can access private data or services. |

## Operational readiness

| Work | Status | Next outcome |
| --- | --- | --- |
| Registry verification rollout | In Progress | Configure target registry credentials and allowlists, verify approved revisions, and retain exact-digest artifacts required by `preload_only` deployments. |
| Data recovery drills | In Progress | Rehearse rollback in the target environment with a pinned release and migration snapshot. Verify recovery from off-host database and private-volume copies. [Backup and restore](../operations/BACKUP-RESTORE.md) |
| Deployment health verification | Partial | `./nukelabctl doctor --post-upgrade` now verifies a running deployment read-only: service containers, public API health and release version, image identity, Alembic head compatibility, Celery worker/Beat presence, unresolved recovery rows, and optional batch-job tables. A staging pinned upgrade/rollback rehearsal is still pending. [Upgrade runbook](../operations/PRODUCTION-DEPLOYMENT.md#upgrade-runbook) |
| Repository rules | Partial | Confirm required `CI Gate` and `Security Gate` checks, signed commits on `main`, and protected release tags. The CI signing check remains advisory. [Security workflow](../../.github/workflows/security.yml) |
| Podman verification | Partial | Verify exact-digest registry pulls, hardening, and crash recovery on Podman. The recorded runtime exercises used Docker. |
| Independent security assessment | Future | Complete an external assessment and retest before public launch, alongside verification of the deployment and recovery procedure. [Assessment plan](../security/PENETRATION-TEST-PLAN.md) |

## Deferred work

- **Batch retries and parameter sweeps** follow reliable single-job execution.
- **Blue-green cutover and automatic rollback** remain deferred. Pinned upgrades and snapshot-based rollback are available today.
- **Vault or sealed-secrets integration** follows agreement on workload credential requirements.
- **Kubernetes migration** follows measured saturation of a large single host (32+ cores, 128 GB+ RAM) and evidence that workloads need to be distributed.
- **Marketplace and plugins** remain deferred.

## Delivery history

- [Changelog](../../CHANGELOG.md) for changes by release.
- [Implementation phases](IMPLEMENTATION-PHASES.md) for delivered capabilities and verification coverage.
- [Decision log](DECISION-LOG.md) for architecture and process decisions.
