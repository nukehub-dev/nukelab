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
and pending cancellation. Claims and cancellation serialize under admission.
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
the original mutable tag. Missing artifacts fail explicitly. The current driver
records local-only identities; repository digests alone are not registry
verification, and matching approval on a different installation is not automated.
A manifest neither backs up user files nor freezes host drivers/external services.

## Worker ownership and recovery

Runtime-capable Celery tasks use `operation_runner.py` with a task-local loop,
fresh DB sessions and a fresh driver. Cooperative cancellation is joined before
resources close. Schedules, health restart, idle shutdown, billing enforcement,
auto-stop and volume quota enforcement call the shared lifecycle services.
Enforcement stops carry the observed server version into termination admission;
health probes discard stale results and pass sampled authority into restart.

Uncertain operations remain protected and block conflicting mutations. Automated
crash adoption and operator-facing reconciliation are not complete. Never clear
an uncertain journal, mount guard or GPU reservation solely because a worker or
HTTP deadline expired. See [operations guidance](../operations/OPERATIONS.md)
for upgrade and investigation requirements.

## Code ownership

| Responsibility | Location under `backend/app/` |
|---|---|
| HTTP and owner queue routes | `api/servers.py`, `api/server_queue.py` |
| Admission and queue dispatch | `services/server_launch_service.py`, `services/server_queue_dispatch_service.py` |
| Existing-server operations | `services/server_lifecycle_service.py`, `services/server_termination_service.py` |
| Action journal and fencing | `services/server_operation_service.py` |
| Runtime composition and driver | `container/spawner.py`, `container/docker_driver.py` |
| Scheduling and health | `services/schedule_service.py`, `services/health_check_service.py` |
| Task ownership | `tasks.py`, `worker.py`, `services/operation_runner.py` |

Offline private-volume recovery shares the volume operation guard with launch,
file mutation, sharing and deletion. The separate helper captures only detached
private volumes and restores into a new protected destination. See
[recovery operations](../operations/BACKUP-RESTORE.md#private-user-volume-recovery).
Verified registry portability, automatic crash adoption and combined real-stack
acceptance remain separate delivery gates.
