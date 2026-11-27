# NukeLab Roadmap

**Current baseline** is `v2.3.0`. Users can queue server launches, recreate approved environments, and recover private volumes offline. The platform can reconcile interrupted operations and match registry-verified environments across installations.

## Product priorities

| Work | Status | Next outcome |
| --- | --- | --- |
| Scientific batch jobs | Future | Run one command in an approved environment using existing plans and resource limits. Show queued and running states, support cancellation, and retain the exit status, logs, and outputs. |
| Scoped workload secrets | Future | Define credential ownership, authorized injection, rotation, and redaction for workloads that need access to private data or services. |

## Operational readiness

| Work | Status | Next outcome |
| --- | --- | --- |
| Registry verification rollout | In Progress | Configure target registry credentials and allowlists, verify approved revisions, and retain exact-digest artifacts required by `preload_only` deployments. |
| Data recovery drills | In Progress | Rehearse rollback in the target environment with a pinned release and migration snapshot. Verify recovery from off-host database and private-volume copies. [Backup and restore](../operations/BACKUP-RESTORE.md) |
| Deployment health verification | Partial | Add repeatable health checks after a pinned upgrade. The existing runbook uses an explicit restart and manual verification. [Upgrade runbook](../operations/PRODUCTION-DEPLOYMENT.md#upgrade-runbook) |
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
