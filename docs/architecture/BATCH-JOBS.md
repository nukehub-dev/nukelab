# Batch Jobs

Single-run batch jobs execute one noninteractive command in an approved
environment using an existing plan, one owned private volume, and the same
CPU/memory/disk reservations as server launches. A job is not an interactive
server: it has no public route, no network, no shell parsing, no restart policy,
and no scoped secret injection.

## Surfaces and permissions

| Surface | Route | Requirement |
|---|---|---|
| Owner capabilities | `GET /api/jobs/capabilities` | JWT + `jobs:read_own` |
| Eligible revisions | `GET /api/jobs/eligible-revisions` | JWT + `jobs:read_own` |
| Submit | `POST /api/jobs` | JWT + `jobs:write_own`, submission enabled, cohort match, `Idempotency-Key` |
| List/detail/logs | `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/logs` | JWT + `jobs:read_own` |
| Cancel | `POST /api/jobs/{id}/cancel` | JWT + `jobs:write_own` |
| Admin read-only view | `GET /api/admin/jobs`, `GET /api/admin/jobs/{id}` | JWT + `operations:read_all` + `ADMIN_ACCESS` |

Owner routes are JWT-only; API-token authentication is not accepted. Foreign and
unknown job IDs both return `job_not_found` (404). Disabling submission does not
disable reads, logs, or cancellation.

Submission is disabled by default. `BATCH_JOBS_ALLOWED_USER_IDS` is an optional
comma-separated pilot cohort; when empty, the `jobs:write_own` grant defines
eligibility. A nonempty cohort narrows submission and admission eligibility.
Admission re-reads the current permission grant and cohort; cancellation
requires current write permission but remains available to an owner outside the
cohort, so removing access does not erase existing history.

## Journal

`batch_jobs` stores the durable owner intent and execution journal. Key groups:

- Request identity: owner, idempotency-key hash, canonical request fingerprint.
- Frozen selection: revision, plan, volume, literal `argv`, maximum runtime.
- Public state: `queued`, `starting`, `running`, `cancelling`,
  `recovery_required`, `succeeded`, `failed`, `cancelled`, `timed_out`,
  `expired`; plus a sanitized `reason_code`.
- Checkpoints: queue expiry, reservation, create request, start request, start
  observation, runtime deadline, stop request, finish.
- Immutable submission snapshots for the approved revision, plan values, and
  volume display identity.
- Reservation and exclusion: `reservation_active`, reserved CPU/memory/disk,
  volume operation ID and fencing token.
- Runtime identity, fenced executor and heartbeat, terminal result, cleanup
  state, log metadata, and zero-cost billing fields.

`batch_job_logs` keeps one bounded payload row per job with encoding, truncation,
size, capture time, and expiry. `job_writer` is an exclusive
`volume_operations.kind`; a partial unique index allows one active backup,
restore, or job-writer guard per volume.

The migrations are `b7d4e1c9a2f5` (tables/indexes) and `e2c7a9f4d6b1`
(reservation columns and `job_writer` exclusion). The current Alembic head is
`e2c7a9f4d6b1`. See [DATA-MODEL.md](DATA-MODEL.md) for field-level detail.

## Lifecycle

```
queued ──admit──> starting ──observed running──> running ──exit──> succeeded
   │                 │                            │              failed
   │                 ├──cancel────────────────────┤              cancelled
   │                 │                            └──deadline──> timed_out
   ├──expire/cancel─> expired/cancelled
   └─────────────── starting/running ──unverifiable──> recovery_required
```

- `queued` waits for an eligible revision, plan, volume, owner/fleet slot, and
  shared capacity. Queue age is bounded by `BATCH_JOBS_QUEUE_TTL_SECONDS`.
- `starting` owns a committed reservation and the exclusive volume guard while
  the runtime is prepared and created.
- `running` begins when the start is observed; the deadline is calculated from
  the observed start, not from submission.
- `cancelling` records a stop request. Resources stay reserved until termination
  and a proof-backed terminal result.
- `recovery_required` means the runtime outcome cannot be verified. It retains
  its reservation and volume guard and is never released by elapsed time.
- `succeeded` and `failed` come from observed exit evidence. `cancelled` and
  `timed_out` are applied only after a stop is confirmed; a natural exit that
  finished before the stop request or deadline is preserved instead.

## Submission and idempotency

Submission validates a bounded name, literal argument vector, and maximum
runtime. It requires an approved, non-revoked environment revision the actor can
use, an active CPU-only zero-cost plan the actor can use, and an owned active
private volume. Plans with GPUs or a nonzero hourly cost are rejected.

`Idempotency-Key` is mandatory (1–128 visible ASCII characters). The unique
owner/key-hash index plus the canonical request fingerprint make retries safe:
the same payload returns the original job with `replayed=true` and HTTP 200; a
different payload with the same key returns 409. A new submission returns 202.

Only zero-cost billing is implemented. `billing_mode` is always `zero_cost`,
`charged_credits` stays zero, and `BATCH_JOBS_ALLOW_PAID_PLANS` is inert. The
capabilities response reports `secrets_enabled=false`.

## Admission

Dispatch selects queued jobs through a durable rotating cursor under the shared
admission lock. Selection is advisory; admission re-reads the row.

Before taking the admission lock, admission proves the exact approved artifact
from the frozen snapshot and immutable revision metadata. Registry-verified
revisions must resolve to the approved platform digest and matching local
identity; local-only revisions must match the recorded local image ID and
platform. The same proof applies to an approved toolchain image. A missing
artifact fails the queued job without reserving anything. A `preload_only`
registry policy never pulls during this step.

Under the admission lock, admission rechecks:

- job state, queue expiry, owner activity, current `jobs:write_own`, and cohort;
- current revision approval, revocation, template activity, and identity match;
- plan activity, actor access, CPU-only shape, unchanged plan snapshot, and
  zero cost;
- owned private active volume and availability;
- per-owner active cap and the optional fleet cap (submission separately bounds
  the queued count);
- shared allocatable CPU, memory, and disk pools;
- user quota, including the plan's per-user slot count.

Capacity or a busy volume leaves the job queued with a wait reason. Policy,
quota, or artifact failures finish the queued job without creating a runtime.
Successful admission acquires one `job_writer` guard, writes the reservation and
runtime identity, and commits `starting` exactly once before any runtime I/O.
Active jobs count in `QuotaService` and `ResourcePoolService` accounting.

## Runtime profile

`run_batch_job` runs in `celery-worker` under the shared operation runner. The
lane claims preparation before touching the volume or toolchain, revalidates the
claim before create, and records the deterministic container identity before
claiming start. A duplicate delivery or monitor only inspects the recorded
identity; it never issues a second create or start.

Preparation:

1. Resolve the already-proved image from the admitted runtime identity. Never
   re-resolve a mutable tag.
2. Prepare the immutable toolchain cache read-only when the revision has one.
3. Run a bounded root prep container from the approved job image to fix
   ownership of the single `/work` volume, then remove it. The prep container has
   no network, no capabilities, no user-controlled arguments, and a timeout.
4. Build the sanitized environment from approved template variables, dropping
   platform auth/database/Redis/Celery/SMTP keys and fixed runtime keys, then add
   only job identity and CPU-count values.

The job container is created and then started under separate checkpoints. It
uses:

- fixed UID/GID `65532:65532`, a read-only rootfs, `CapDrop=ALL`,
  `no-new-privileges`, no network, no published ports, no restart policy;
- bounded CPU, memory, pids, `/tmp`, `/home`, and Docker log rotation;
- a literal entrypoint/argument vector with no shell parsing, plus a timeout
  wrapper for the requested maximum runtime;
- exactly one read-write private volume at `/work`, plus optional read-only
  toolchain mounts;
- deterministic name `nukelab-job-<job uuid>` and managed job/fence/workload
  labels.

Observed identity is validated against the job label, fence, workload, expected
image, and name before any stop, start adoption, or finalization.

## Monitoring and finalization

`monitor_batch_jobs` scans bounded active rows, oldest heartbeat first. It
inspects the recorded runtime and the deterministic name; an ambiguous identity
requires recovery. It may start a created container that has no start
checkpoint, but never creates another runtime after a create checkpoint.

Finalization is one fenced transaction owned by
`BatchJobAdmissionService.release_terminal()`: it requires executor termination
proof, writes the terminal state/outcome/exit code and observed runtime identity,
stores the bounded log payload, and releases the volume guard. A caller without
that proof receives `executor_unconfirmed` and the reservation stays protected.
Repeated terminal release is idempotent and never rewrites the recorded result.
An OOM kill is recorded as failed, a nonzero exit as `nonzero_exit`, missing exit
evidence as `runtime_unverifiable`, and the timeout wrapper's 124/137 exit after
the deadline as `timed_out`.

Container cleanup is separate from the result. `cleanup_state` starts `pending`;
the finalizer attempts deletion, records attempts, and leaves a retained
container for a bounded retry. A cleanup failure never changes the execution
outcome. Cleanup also verifies job labels before deleting a name match.

`reconcile_batch_jobs` inspects stale starting/running/cancelling rows and
retries bounded cleanup. A stale heartbeat is an inspection trigger, not
termination proof; there is no TTL takeover. Recovery-required jobs retain their
reservation and guard. The scan persists its bounded, identifier-free freshness
state in `system_settings` (`batch_jobs_recovery_scan_state`). Worker startup
refuses journal work when `batch_jobs` lacks `executor_id`, `heartbeat_at`,
`state`, or `fencing_token`.

Celery Beat schedules `dispatch_batch_jobs`, `monitor_batch_jobs`, and
`reconcile_batch_jobs` using the `BATCH_JOBS_*_INTERVAL_SECONDS` settings.
Metrics expose queued, active, recovery-required, and cleanup-pending job gauges.

## Logs and retention

The runtime captures at most the last 5,000 container log lines and then keeps at
most `BATCH_JOBS_LOG_TAIL_BYTES` (default 256 KiB) of the newest UTF-8 bytes.
Truncation, original byte size, encoding, capture time, and expiry are recorded.
The owner logs endpoint returns at most the configured tail and reports
`truncated` or `expired` rather than implying complete output.

The default retention is `BATCH_JOBS_LOG_RETENTION_SECONDS` (7 days). Expiry is
enforced at read time: after `log_expires_at`, the API returns `expired` with no
text. This release does not schedule a separate physical log-purge task, so
expired payload rows remain until an operator-maintained cleanup.

## Admin visibility

`/admin/jobs` and `GET /api/admin/jobs` are read-only. Rows expose sanitized
state/reason codes, bounded owner/environment/plan/volume display names,
timestamps, reservation and active volume-guard flags, heartbeat age, and
log/cleanup state. Command arguments, logs, environment values, image
references, runtime identity, volume paths, fencing tokens, and executors are
never returned. `can_reconcile` is always false. There is no admin cancel,
retry, reconcile, or manual reservation-release endpoint in this release.

## Access and security checks

- Owner authorization is enforced server-side on every route; foreign IDs are
  indistinguishable from missing IDs.
- Admin visibility requires both the operations read grant and admin access,
  plus a JWT session.
- The batch container cannot reach the network, the Docker socket, or platform
  credentials; it runs non-root with no capabilities and a read-only rootfs.
- Submission bounds argument count/bytes and runtime. The runtime bounds CPU,
  memory, pids, tmpfs, log bytes, and total execution time.
- The `job_writer` guard excludes file mutation, metadata/sharing changes,
  backup/restore, launch mount intent, and volume deletion until proved
  termination.
- Regression coverage lives in `backend/tests/security/test_job_ownership.py`,
  `test_admin_jobs_privacy.py`, the job API/service/runtime/monitor/recovery
  suites, `tests/services/test_batch_job_volume_guard.py`, and
  `tests/container/test_batch_driver.py`. The security test mapping is in
  [PENETRATION-TEST-PLAN.md](../security/PENETRATION-TEST-PLAN.md#batch-job-controls).

## Verification status

Implemented and executed for the 2.4.0 batch-job change set (2026-11-28):

- Backend full suite: 4,995 passed, 6 skipped, 0 failed.
- Frontend: 234 unit tests passed, lint/format/build/type-check passed.
- Targeted mocked browser suites passed: `jobs-ui` (11),
  `guided-first-launch` (9), `admin-jobs-ui` (8), and the existing
  queue/admin-setup regressions (10).
- Real Docker driver smoke passed for root-only `/work` prep, UID 65532,
  `/work` output, timeout exit 124, stop exit 137, and cleanup.
- Shell lint and `docker compose config -q` passed.

Carried gaps:

- No full API→PostgreSQL/Redis/Celery/Docker job has run end to end yet, and the
  required disposable real-stack browser scenario plus worker-death/broker-loss
  interruption drill are not yet wired into CI.
- Writable `/work` disk enforcement and the last-slot capacity/volume race have
  not been rehearsed on the pilot storage; admission uses the existing
  XFS/volume quota configuration.
- No staging pinned upgrade/rollback/off-host restore rehearsal, and no registry
  `preload_only` staging proof.
- Podman batch enablement is not verified.
- Paid credit settlement, scoped workload secrets, job completion
  notifications, and an admin proof-backed reconcile/manual-release path are not
  implemented.

## Related documents

- [OVERVIEW.md](OVERVIEW.md) for the platform request flow
- [DATA-MODEL.md](DATA-MODEL.md) for table and index detail
- [OPERATIONS.md](../operations/OPERATIONS.md#115-batch-job-rollout-and-drain) for rollout and drain
- [PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md#batch-job-rollout)
- [ENV-VARS.md](../reference/ENV-VARS.md#batch-jobs)
- [PENETRATION-TEST-PLAN.md](../security/PENETRATION-TEST-PLAN.md#batch-job-controls)
