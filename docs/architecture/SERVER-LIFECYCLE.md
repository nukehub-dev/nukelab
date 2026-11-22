# NukeLab Server Lifecycle

Creation, queue dispatch, user/admin/bulk actions, logout stops, schedules and health restarts
share admission and lifecycle services. Routes retain authentication, token scope,
resource ownership, cross-user reason and audit checks.

## Admission and waiting

`server_launch_service.py` resolves approved immutable image identities outside
admission locks, then rechecks current owner permissions, plan/environment access,
credits, quota and volume access. Read Committed transactions acquire the shared
admission lock before fresh accounting queries. Reservations commit before runtime I/O.

Available capacity produces a stable `starting` server, immutable launch intent,
GPU allocations and mount guards. Scarcity produces HTTP 202 with a typed queue
request, preserving normalized volume paths, modes and explicit capacities. Waiting
creates no user data volumes, running server or credit debit. Immediate success
retains the normal server response.

The owner-scoped `/server-queue` router exposes capability discovery, list/detail
and pending cancellation. Claims serialize under admission; cancellation is an
atomic pending-only transition that loses to a claim and returns conflict once
launch has started. A `starting` request is reconciled against its linked create
operation: a verified success becomes `started`, a safe failure becomes `failed`,
and an uncertain outcome stays `starting` with `recovery_required`. An orphaned
`starting` row without an operation is cancelled only after runtime absence is
proved from its recorded container ID, managed server label, or deterministic
launch name; missing identity or an unavailable runtime inspection keeps it
operator-visible with `recovery_required`. The admin queue view is read-only and
cross-owner; there is no admin cancellation or retry action.
`server_queue_dispatch_service.py` scans bounded batches in priority/time/ID order
and persists a rotating cursor so non-fitting early requests cannot hide later
candidates indefinitely. Positions describe ordering, not a guaranteed start time.
The frontend waiting tab polls active requests and links successful requests to
the actual server name; account changes invalidate owner-scoped queue state.

## Fenced lifecycle operations

`server_operation_service.py` journals immutable action intent and a fencing token.
A partial unique index permits one active prepared, executing or uncertain action
per server. Only the successful prepared-to-executing claimant performs runtime I/O.
Replays do not start another executor. Completion requires verified runtime or
executor termination evidence; elapsed time alone never authorizes takeover.

| State | Meaning |
|---|---|
| `starting` | Launch/replacement reserved; uncertainty may require reconciliation |
| `running` | Runtime identity and readiness verified |
| `stopping` | Termination reserved; resources remain protected until verified |
| `stopped` | Termination verified or an existing stopped server retained |
| `error` | Failed server state outside an active protected operation |

`server_lifecycle_service.py` implements start, restart and configuration edits.
Starting an already running server is idempotent. Recreation uses the captured
approved revision, even if the mutable environment template has changed. Explicit
selection changes resolve a new approved revision. Each successful recreation
records a new immutable launch generation. Image resolution and edits compare the
initial server version again under admission, rejecting a stale selection if
an intervening action has completed. Legacy servers missing plan/environment selection can resume an existing verified
non-exclusive-GPU container; missing runtime identity cannot authorize recreation.
An unrecorded server with a valid selection captures its first approved revision
for a new recreation and records only that observed generation. No historic proof
is backfilled from today's template.

Replacement holds the larger old/new resource reservation and the union of mount
and GPU guards until the exact predecessor is verified gone. Runtime mutations
check managed owner/server labels. Reserved names derive from the stable server
UUID rather than the display name.

Queue dispatch, schedules, health restarts and lifecycle enforcement execute in
`celery-worker`, so that container receives the same runtime/security settings as
the API (`CONTAINER_HARDENING_ENABLED`, runtime selection, server-auth keys,
public URL, GPU and resource-pool limits). Missing worker configuration changes
only background-admitted launches and can silently produce different containers.
A newly created private volume selected for launch receives a one-time mount-root
permission initialization for the non-root runtime; existing data volumes are
never relabeled or recursively chmodded. The read-only root filesystem includes
a writable `/home`, so a server with only explicit non-home data mounts can
initialize its runtime home; without a home volume that home is ephemeral.

`server_termination_service.py` reserves stop/delete before I/O, verifies runtime
identity and removal, then releases GPU/mount guards and updates accounting under
the fence. A running server with a missing container ID cannot be declared stopped
without evidence. Unknown outcomes return a sanitized error and retain protection.
Billing reconciliation and notifications occur outside admission locks.

Status reads probe outside locks, then compare the observed container ID, row
version and active operation under admission before applying a status change.
They cannot convert an active `starting`/`stopping` reservation into a released state.
Paused runtimes keep their compute/memory reservation because pausing does not
release their host memory.

## Runtime and toolchain identity

The reserved spawner selects exact local image IDs, requires readiness and refuses
destructive runtime adoption or missing existing data volumes. Readiness checks
both the container endpoint and its public route through internal Traefik.
Toolchain caches are keyed by immutable identity/platform/layout and mounted
read-only. Incomplete or mismatched caches fail closed; uncertain helper outcomes
retain atomic locks without TTL takeover. Existing data and read-only mounts are
not chmodded as part of launch. Repository digest metadata alone does not prove
registry portability.

## Provenance, export and approved recreation

The server detail page shows the last verified launch, requested/observed artifact
identities, capture time and recorded limitations. A newer starting or uncertain
replacement does not make an older record proof of the current runtime. Legacy
servers without records remain explicitly unrecorded. Exports select the displayed
immutable launch and return its saved sanitized manifest, never today's template
or a raw runtime inspection. Revocation blocks recreation while retaining history.
Admins verify and revoke revisions from **Administration → Environments** →
**Revisions**; verify resolves current references to exact platform digests, and
revoke is idempotent with no un-revoke path. Revoking the last selectable revision
requires explicit confirmation.

Registry verification is a separate decision from approval. `off` performs no
registry I/O, `prefer` records a truthful local-only fallback when resolution is
unavailable, and `require` fails closed. A verified revision stores the canonical
repository, exact platform manifest digest, OS/architecture/variant and index
digest; a tag-pulled index digest is not proof of the platform artifact. Moving a
tag never changes an existing approval. Re-verifying a moved tag creates a new
captured revision only through the explicit admin action, using the `require`
policy and exact-digest local proof.

Registry-verified, portable configurations also receive a portable fingerprint
over normalized configuration and verified platform identities. Cross-install
manifest import matches active revisions by that fingerprint only; multiple
matching templates are reported as ambiguous. Local-only manifests keep strict
local revision matching. Portable matching never creates approval or runs
verification implicitly.

`server_recreation_service.py` validates either an owned source launch or a bounded
strict manifest against an existing approved revision. Imports do not create
approval or grant access. The owner UI supports source recreation and imported
JSON; API cross-user history retains JWT/reason/audit rules, while source launch
IDs remain owner-only. Read-only owners can inspect/export without creating work.

Preview requires both read and write permissions/scopes because it discloses
saved metadata. Final submission rechecks current approval and uses the normal
write/manage boundary. A preview grants no permission, capacity or artifact lease.
History/export and preview responses use private no-store caching. A read-scoped
API token is not advertised as eligible to recreate without manage scope.

Recreation asks for a new name, current plan and a deliberate fresh/existing volume
for each logical requirement. Paths and modes match the validated preview; home
aliases map to the actor's home, and source volume IDs are never copied. Imported
resource descriptions and variable names grant no entitlement or environment-value
override. Data destinations cannot overlap system security mounts or approved
read-only toolchain roots, including parent and child paths.

`submit_pinned()` verifies exact local artifact identity/platform before reservation
and invokes the same direct/queued admission boundary. It does not resolve or pull
the original mutable tag. A registry-verified revision may ensure the exact
approved platform digest locally; with `on_demand`, only that digest is pulled,
under a per-digest PostgreSQL advisory lock and re-proved afterward. With
`preload_only`, a missing or platform-mismatched artifact fails closed. Local-only
revisions require the recorded local image identity. Missing artifacts fail
explicitly rather than falling back to a newer tag. Repository digest metadata
alone does not prove registry portability, and a manifest neither backs up user
files nor freezes host drivers/external services.

## Worker ownership and recovery

Runtime-capable Celery tasks use `operation_runner.py` with a task-local loop,
fresh DB sessions and a fresh driver. Cooperative cancellation is joined before
resources close. Schedules, health restart, idle shutdown, billing enforcement,
auto-stop and volume quota enforcement call the shared lifecycle services.
Enforcement stops carry the observed server version into termination admission;
health probes discard stale results and pass sampled authority into restart.

Recovery starts from durable liveness evidence, not elapsed time. Every API
uvicorn worker and the single Celery worker process register a process-lifetime
`worker_heartbeats` row with container identity, exact container start time, PID
and single-process-container status; Celery Beat does not register. Long launch,
backup and restore I/O refreshes the active row's `executor_id` and `heartbeat_at`
only while its fence stays active. A stale worker or operation heartbeat is an
inspection trigger or a stall observation. It never releases a reservation,
proves termination, or authorizes takeover. API executors remain ambiguous unless
the container stopped/restarted or a graceful marker was written after draining.
A single-process worker container can also be resolved by a fresh replacement
executor for the same container incarnation. `docker restart` keeps the container
ID, so exact container start time is the incarnation token.

`operation_reconciliation.py` is read-only evidence classification. It combines
liveness (alive, stopped, ambiguous) with runtime/artifact evidence (present,
absent, ambiguous) and returns a bounded terminal outcome only when the evidence
supports one, otherwise `recovery_required` or a deferred/no-terminal result.
Launch success requires a running, healthy container carrying
the matching launch/server labels, the approved runtime identity and platform
(including the verified digest when applicable), the expected generation and
readiness through the container and, when configured, internal Traefik. A
proof-backed success may adopt an `uncertain` launch. Failure requires stopped
liveness and proven runtime absence; a live executor is never failed from runtime
health alone. A termination succeeds only when the runtime is absent and the
predecessor is verified gone.
Backup success requires helper termination plus completion metadata and an archive
checksum. Restore success requires the same verified completion metadata and
helper termination; a `restoring` destination is activated from that metadata,
while an already-active destination must match the recorded size. Proof-backed
volume success still goes through the recovery service's completion hook.

`operation_finalizer.py` is the only mutation boundary. It re-reads the journal
row under admission and a row lock, verifies fence, identity and active state, and
applies the decision once without retrying external I/O. Terminal rows are
immutable; an unexpected finalization failure attempts to degrade the row to
`recovery_required` instead of partially releasing it. Launch uncertainty is
stored as `uncertain`; volume uncertainty is stored as `recovery_required`. Both
retain mount guards, GPU allocations, storage reservations and artifacts.

`operation_reconciler.py` schedules a first scan after
`RECOVERY_INITIAL_DELAY_SECONDS`; Celery Beat then runs it every
`RECOVERY_SCAN_INTERVAL_SECONDS`. It selects a bounded, oldest-first batch,
round-robins launch/backup/restore work so one kind cannot starve another, and
defers live executors or rows without a proof-backed outcome. An unclaimed
`prepared` successor younger than `RECOVERY_PREPARED_GRACE_SECONDS` is left
claimable; an older one may fail without runtime side effects. The scanner never
retries `uncertain` or `recovery_required` rows without new proof. Queue recovery
resolves `starting` requests through their linked create operation and runtime
proof, and never blindly requeues or cancels work.

Applied transitions notify the operation owner after commit. One attention
notification is stored per operation and terminal state, a recovery completion is
sent only after an attention event, and one bounded reminder per operation is
allowed every 24 hours while work remains unresolved. Reminder delivery runs daily
at 08:00 UTC in bounded batches. Delivery is best effort and never changes recovery
state or releases protection.

Admins inspect sanitized operation and queue views and may request reconciliation
from the operations console. Reconcile reruns the same read-only inspector and
asks the fenced finalizer to apply only a proof-backed outcome. It requires a
bounded reason and audit entry, returns conflict with diagnostics when proof is
ambiguous, and has no force path, TTL takeover, or admin cancel/retry. Never clear
an uncertain journal row, mount guard or GPU reservation solely because a worker
or HTTP deadline expired. See [operations guidance](../operations/OPERATIONS.md#11-recovery-operations-and-upgrades)
for upgrade and investigation requirements.

## Code ownership

| Responsibility | Location under `backend/app/` |
|---|---|
| HTTP and owner queue routes | `api/servers.py`, `api/server_queue.py` |
| Provenance and recovery routes | `api/server_provenance.py`, `api/volume_backups.py` |
| Admission and queue dispatch | `services/server_launch_service.py`, `services/server_queue_dispatch_service.py` |
| Launch validation, recreation and provenance | `services/server_launch_validation.py`, `services/server_recreation_service.py`, `services/server_provenance_service.py` |
| Existing-server operations | `services/server_lifecycle_service.py`, `services/server_termination_service.py` |
| Action journal and fencing | `services/server_operation_service.py` |
| Recovery inspection and finalization | `services/operation_reconciliation.py`, `services/operation_finalizer.py`, `services/operation_reconciler.py` |
| Recovery observability and notifications | `services/recovery_metrics.py`, `services/recovery_notifications.py` |
| Admin operations and queue visibility | `api/admin_operations.py`, `api/admin_queue.py` |
| Volume operation guard and recovery | `services/volume_operation_service.py`, `services/volume_backup_service.py`, `services/volume_recovery_runtime.py` |
| Runtime composition and driver | `container/spawner.py`, `container/docker_driver.py` |
| Scheduling and health | `services/schedule_service.py`, `services/health_check_service.py` |
| Task ownership | `tasks.py`, `worker.py`, `services/operation_runner.py` |

Offline private-volume recovery shares the volume operation guard with launch,
file mutation, sharing and deletion. The separate helper captures only detached
private volumes and restores into a new protected destination. Recovery
orchestration runs in `celery-worker` and is configured with the
`VOLUME_BACKUP_*` settings; see the environment reference for values. See
[recovery operations](../operations/BACKUP-RESTORE.md#private-user-volume-recovery).
Local-only revisions still require their exact local image IDs. Registry-verified
revisions can use the approved platform digest, and `preload_only` intentionally
refuses to pull a missing artifact. The combined real-stack acceptance suite runs
locally; production rollback remains an operator procedure using a pinned image
and snapshot restore.
