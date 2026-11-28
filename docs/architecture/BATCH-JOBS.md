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
| Admin visibility | `GET /api/admin/jobs`, `GET /api/admin/jobs/{id}` | JWT + `operations:read_all` + `ADMIN_ACCESS` |
| Proof-only reconcile | `POST /api/admin/jobs/{id}/reconcile` | JWT + `operations:manage_all` + `ADMIN_ACCESS` + bounded reason |

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
  state, log metadata, and billing journal (`billing_mode`, `authorized_credits`,
  `billing_rate_per_hour`, `billing_state`, `charged_credits`,
  `billing_transaction_id`).

`batch_job_logs` keeps one bounded payload row per job with encoding, truncation,
size, capture time, and expiry. `job_writer` is an exclusive
`volume_operations.kind`; a partial unique index allows one active backup,
restore, or job-writer guard per volume. Expired log payloads are physically
removed by a bounded scheduled purge; the terminal result and log metadata stay
intact.

`credit_holds` stores one authorization per paid job: owner and job references,
held amount, lifecycle state (`held`/`settled`/`released`), captured charge,
unpaid remainder, the single `batch_job_usage` transaction when the charge is
positive, and creation/settlement times. A unique job index prevents duplicate
authorizations; `(user_id, state)` serves spendable-balance sums.

The migrations are `b7d4e1c9a2f5` (tables/indexes), `e2c7a9f4d6b1`
(reservation columns and `job_writer` exclusion), and `f1a2b3c4d5e6` (billing
journal and `credit_holds`). The current Alembic head is `f1a2b3c4d5e6`. See
[DATA-MODEL.md](DATA-MODEL.md) for field-level detail.

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
use, an active CPU-only plan the actor can use, and an owned active private
volume. Plans with GPUs are rejected. A nonzero hourly cost is accepted only when
`BATCH_JOBS_ALLOW_PAID_PLANS=true`.

`Idempotency-Key` is mandatory (1–128 visible ASCII characters). The unique
owner/key-hash index plus the canonical request fingerprint make retries safe:
the same payload returns the original job with `replayed=true` and HTTP 200; a
different payload with the same key returns 409. A new submission returns 202.

Billing is frozen from the plan snapshot at submission. A zero-cost plan creates
no hold. A paid plan creates one `credit_holds` row for
`ceil(rate × max_runtime_seconds / 3600)` credits (minimum 1) in the same
transaction as the job, after taking the shared admission lock and locking the
user row. Insufficient spendable balance returns 402 `insufficient_credits` and
creates neither row. The capabilities response reports `billing_mode=paid` only
when the paid flag is on and always reports `secrets_enabled=false`.

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
- plan activity, actor access, CPU-only shape, unchanged plan snapshot, and the
  paid flag when the frozen cost is nonzero;
- for a paid plan, one `held` authorization whose amount matches
  `authorized_credits` and a freshly locked user balance that still covers it;
- owned private active volume and availability;
- per-owner active cap and the optional fleet cap (submission separately bounds
  the queued count);
- shared allocatable CPU, memory, and disk pools;
- user quota, including the plan's per-user slot count.

Capacity or a busy volume leaves the job queued with a wait reason. Policy,
quota, billing, or artifact failures finish the queued job without creating a
runtime and release any hold. Successful admission acquires one `job_writer`
guard, writes the reservation and runtime identity, and commits `starting`
exactly once before any runtime I/O. Active jobs count in `QuotaService` and
`ResourcePoolService` accounting.

## Billing and credits

Zero-cost plans never create a hold and keep `billing_state="none"`. Paid plans
freeze `billing_rate_per_hour` and `authorized_credits` on the job and create one
`held` row in `credit_holds` at submission. Every debit path — interactive
launch, restart/resume, periodic server billing, stop reconciliation, and admin
deductions — uses spendable balance (total balance minus active held amounts),
so an interactive action cannot consume credits reserved for a queued or running
job.

Queued cancellation, queue expiry, admission rejection, and pre-start failure
release the hold at zero charge. A proof-backed terminal result settles one
bounded observed interval:

- `seconds = 0` when the start was never observed; otherwise
  `(finished_at - started_at)` clamped to `[0, max_runtime_seconds]`.
- `charge = 0` when `seconds == 0` or the rate is zero; otherwise
  `min(authorized, max(1, ceil(rate × seconds / 3600)))`.
- The unused authorization (`authorized - bounded charge`) is refunded. If the
  user balance cannot cover the bounded charge, the captured charge is clamped
  to the balance and the remainder is stored as unpaid debt — settlement never
  raises and never rolls back the terminal result.
- A positive charge writes exactly one `batch_job_usage` transaction carrying
  job, rate, authorization, observed seconds, refund and unpaid metadata. A zero
  charge writes none.

`recovery_required` retains the hold until the proof-only finalizer settles or
releases it. Owner and admin job responses expose only mode, charged,
authorized, rate, and state; hold ids and transaction internals stay private.

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
stores the bounded log payload, settles the credit hold from the observed
runtime, and releases the volume guard. A caller without that proof receives
`executor_unconfirmed` and the reservation and hold stay protected.
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

Celery Beat schedules `dispatch_batch_jobs`, `monitor_batch_jobs`,
`reconcile_batch_jobs`, and the bounded `purge_batch_job_logs` using the
`BATCH_JOBS_*_INTERVAL_SECONDS` settings. Metrics expose queued, active,
recovery-required, and cleanup-pending job gauges.

A `recovery_required` row can be settled only through the proof-only admin
reconcile route. The route reruns a read-only classifier and then invokes the
same fenced finalizer with `executor_terminated=True`. The classifier accepts an
exited runtime with its recorded identity and exit evidence, or an absent
runtime behind a recorded create/start checkpoint when the job heartbeat is
stale. Running, unrecorded, mismatched, or otherwise ambiguous evidence returns
409 `proof_insufficient` and changes nothing. A non-`recovery_required` active
row returns 409 `job_not_reconcilable`; an already-terminal row is an idempotent
200. The operator reason and bounded outcome/proof metadata are audited; audit
availability is required before an applied transition.

## Logs and retention

The runtime captures at most the last 5,000 container log lines and then keeps at
most `BATCH_JOBS_LOG_TAIL_BYTES` (default 256 KiB) of the newest UTF-8 bytes.
Truncation, original byte size, encoding, capture time, and expiry are recorded.
The owner logs endpoint returns at most the configured tail and reports
`truncated` or `expired` rather than implying complete output.

The default retention is `BATCH_JOBS_LOG_RETENTION_SECONDS` (7 days). Expiry is
enforced at read time: after `log_expires_at`, the API returns `expired` with no
text. The scheduled `purge_batch_job_logs` task then deletes expired payload
rows in bounded batches (`BATCH_JOBS_LOG_PURGE_BATCH_SIZE`) every
`BATCH_JOBS_LOG_PURGE_INTERVAL_SECONDS`, sets `log_state="expired"`, and leaves
the terminal result, timestamps, billing, cleanup state, and reservation fields
untouched. Repeated runs are idempotent.

After a new terminal result commits, the owner receives one in-app notification
with the job reference, bounded name, terminal state, and a `/jobs/<id>` link.
Deduplication is per job and terminal event. Delivery is best effort: a
notification failure never changes the result, reopens the job, or releases a
reservation or volume guard.

## Admin visibility

`/admin/jobs` and `GET /api/admin/jobs` expose sanitized cross-owner state.
Rows include reason codes, bounded owner/environment/plan/volume display names,
timestamps, reservation and active volume-guard flags, heartbeat age, and
log/cleanup state. Command arguments, logs, environment values, image
references, runtime identity, volume paths, fencing tokens, and executors are
never returned. `can_reconcile` is true only for a `recovery_required` row when
the caller also has `operations:manage_all`.

The manage-gated row action opens a reason dialog and posts to
`POST /api/admin/jobs/{id}/reconcile`. It renders the server result only after a
confirmed response and never optimistically changes the row. Proof-insufficient
or non-reconcilable responses leave the row and its protection unchanged. There
is no admin cancel, retry, force, or manual reservation-release endpoint.

## Access and security checks

- Owner authorization is enforced server-side on every route; foreign IDs are
  indistinguishable from missing IDs.
- Admin visibility requires both the operations read grant and admin access,
  plus a JWT session. Reconciliation additionally requires the operations manage
  grant and a bounded audit reason; proof remains authoritative over the reason.
- The batch container cannot reach the network, the Docker socket, or platform
  credentials; it runs non-root with no capabilities and a read-only rootfs.
- Submission bounds argument count/bytes and runtime. The runtime bounds CPU,
  memory, pids, tmpfs, log bytes, and total execution time.
- The `job_writer` guard excludes file mutation, metadata/sharing changes,
  backup/restore, launch mount intent, and volume deletion until proved
  termination.
- Regression coverage lives in `backend/tests/security/test_job_ownership.py`,
  `test_admin_jobs_privacy.py`, `test_paid_job_holds.py`, the job
  API/service/runtime/monitor/recovery/billing/credit-hold suites,
  `tests/services/test_batch_job_volume_guard.py`, and
  `tests/container/test_batch_driver.py`. The security test mapping is in
  [PENETRATION-TEST-PLAN.md](../security/PENETRATION-TEST-PLAN.md#batch-job-controls).

## Verification status

Implemented and executed for the 2.4.0 batch-job change set (2026-11-28):

- Backend full suite: 5,088 passed, 6 skipped, 0 failed.
- Frontend: 246 unit tests passed; lint/format/type-check/build passed.
- Targeted mocked browser suites passed: `jobs-ui` (11),
  `guided-first-launch` (9), `admin-jobs-ui` (13), and the existing
  queue/admin-setup regressions (10).
- Real API→PostgreSQL/Redis/Celery/Docker `@jobs-runtime` scenario passed on a
  rebuilt disposable stack. Capacity queueing, exactly one hardened runtime
  (UID 65532, read-only rootfs, `CapDrop=ALL`, no network, no ports, no restart),
  `/work` output, bounded logs, nonzero exit, cancellation, owner isolation,
  post-cleanup results, and zero-cost billing were verified.
- Worker-death and Redis-broker-loss interruption drills passed: one job row,
  one create/start event, one terminal result, one released guard, zero negative
  credit transactions, and cleanup complete.
- Last-slot CPU/memory/disk and volume writer/mount/backup/restore/share/delete
  races passed, including retained `recovery_required` protection.
- Storage capability and fail-closed submission/admission coverage passed. The
  current test host has no kernel-enforced project quota, so an actual over-cap
  write remains a target-storage check.
- Shell lint, `docker compose config -q`, and `./nukelabctl selftest` passed.

Carried gaps:

- The explicit `test-browser-jobs` CI job and nightly interruption-drill workflow
  have not yet run on a GitHub runner.
- An over-cap write on XFS project-quota storage still needs target-storage
  evidence. The capability gate can fail the pilot closed when enforcement is
  required.
- The interruption drill currently kills the worker/broker while the job is
  running; reserve-before-create, created-before-start, and pre-admission broker
  loss variants are not separately exercised.
- No staging pinned upgrade/rollback/off-host restore rehearsal, and no registry
  `preload_only` staging proof.
- Podman batch enablement is not verified.
- Paid hold/settlement code and its migration are implemented but the paid
  billing integration, concurrency, and migration suites have not been executed
  yet; paid plans remain disabled by default. Scoped workload secrets are not
  implemented; the pilot stays secrets-disabled.

## Related documents

- [OVERVIEW.md](OVERVIEW.md) for the platform request flow
- [DATA-MODEL.md](DATA-MODEL.md) for table and index detail
- [OPERATIONS.md](../operations/OPERATIONS.md#115-batch-job-rollout-and-drain) for rollout and drain
- [PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md#batch-job-rollout)
- [ENV-VARS.md](../reference/ENV-VARS.md#batch-jobs)
- [PENETRATION-TEST-PLAN.md](../security/PENETRATION-TEST-PLAN.md#batch-job-controls)
