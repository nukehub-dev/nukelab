# NukeLab Data Model

This document describes the core entities and schema conventions. For exact
fields and constraints, see the SQLAlchemy models under `backend/app/models/`
and the Alembic migrations under `backend/alembic/versions/`.

## Entity overview

Workflow schema additions are additive. `server_launch_intents` persists the selected
revision, complete request, named mounts, original username and claim metadata in
the reservation transaction so a fresh session can reconstruct exact launch intent.
It is private orchestration data, distinct from successful launch provenance. `environment_revisions` stores approved
configuration fingerprints, an optional portable fingerprint, and separate
runtime/toolchain identities; `server_launch_records` stores append-only launch
generations. `worker_heartbeats` records process-lifetime executors used to judge
operation liveness; heartbeat age is an inspection trigger, never termination
proof. Revision services recheck current authorization and revocation. A legacy
server without a captured record remains unrecorded; today's template is not
historical evidence.

`server_queue` can retain versioned launch intent, a plan snapshot, expiry, claim
token and resulting server identity. Null payload/version identifies legacy intent
that the new claim primitive refuses to launch. `volume_operations` persists
writer/mount intents and exclusive backup/restore protection, including uncertain
executor outcomes. Owner APIs and task orchestration use these records for
queueing, approved recreation and offline private-volume recovery. Runtime
uncertainty preserves protection until explicit verified reconciliation.

`batch_jobs` keeps single-run command intent and execution independent of
`servers`; a job never creates a Server row. Its reservation participates in the
same quota/resource-pool accounting, and `job_writer` extends the existing
exclusive volume guard. `batch_job_logs` stores only a bounded retained tail.

`volume_backups` records source metadata, archive format/checksum and bounded
completion counts, operation fence, storage reservation and expiry. Its nullable
source foreign key uses `SET NULL` so completed copies survive source deletion.
Legacy backup rows without a verified format/checksum are never restore points.
`volume_restores` pins a backup and stores the stable new destination identity,
quota/storage reservation, fence and terminal outcome. Active or uncertain restore
rows prevent artifact deletion and retention. Restoring/failed destinations stay
inaccessible; only verified success activates the new volume.

```
+---------+     +---------+     +-------------+       +---------+
|  User   |---->|  Role   |     | Environment |       |  Plan   |
+----+----+     +---------+     +------+------+       +----+----+
     |                                 |                   |
     |    +----------------------------+                   |
     |    |                                                |
     v    v                                                v
  +-------+     +-------------+      +---------------+    +--------------+
  | Server|---->|    Volume   |<-----|SharedWorkspace|    | Credit       |
  +---+---+     +-------------+      |               |    | Transaction  |
      |                              +---------------+    +--------------+
      |
      v
  +------------+
  | Audit Log  |
  +------------+
```

## User

A platform account. Roles are code-defined; quota limits live in
`resource_quotas`, not on the user row.

Key fields: `id`, `username`, `email`, `first_name`, `last_name`,
`password_hash`, `role`, `oauth_provider`/`oauth_id`, `nuke_balance`,
`daily_allowance` (+ time-boxed override), `last_nuke_reset`, `avatar_url`,
`profile_visibility`, `profile`, `preferences`, `security`, `is_active`,
`is_verified`, `email_verified_at`, `credit_requests_blocked`/`_until`,
`last_login`, `login_count`, `created_at`, `updated_at`.

`profile`, `preferences` and `security` are flexible JSON fields. There is no
per-user permission override and no group membership column.

## Role

Roles are predefined in `backend/app/core/roles.py` and expanded through the
permission implications map. Super admins can persist role permission overrides
in `system_settings.role_permissions`; there is no `roles` table.

`ResourceQuota` rows can apply limits by `user_id`, `role`, or `plan_id` and
track current usage totals.

## Server

A user runtime. `environment_id` and `plan_id` are nullable for legacy rows.

Key fields: `id`, `name`, `user_id`, `environment_id`, `plan_id`, `container_id`,
`image`, `volume_id`, `volume_mode`, `status`, `allocated_cpu`,
`allocated_memory`, `allocated_disk`, `allocated_gpu`, `internal_port`,
`external_url`, `health_status`, `health_check_config`, `last_health_check`,
`status_reason`, `stopped_by`, `stop_reason`, `total_cost`, `last_billed_at`,
`expires_at`, `started_at`, `stopped_at`, `last_activity`, `created_at`,
`updated_at`.

Public URLs use `/user/{username}/{server_name}`. Runtime and idle limits come
from platform settings, not server columns.

## EnvironmentTemplate

Admin-created template for a runtime image and optional scientific toolchain.

Key fields: `id`, `name`, `slug`, `description`, `image`, `tool_image`,
`tool_mounts`, `dockerfile`, `packages`, `environment_variables`, `volumes`,
`ports`, `icon`, `color`, `category`, `is_active`, `is_public`, `created_by`,
`created_at`, `updated_at`.

The table is `environment_templates`; the API exposes it as an environment.

## ServerPlan

Resource tier independent of environment.

Key fields: `id`, `name`, `slug`, `description`, `category`, `cpu_limit`,
`memory_limit`, `disk_limit`, `gpu_limit`, `max_servers_per_user`,
`cost_per_hour`, `cooldown_seconds`, `allow_scheduling`, `allow_snapshots`,
`is_public`, `visible_to_roles`, `is_active`, `priority`, `created_at`,
`updated_at`.

`is_public` or a matching `visible_to_roles` entry makes a plan available to a
role. `PlanService` refuses changes that would leave no active plan or no active
plan available to the `user` role.

## Volume

Persistent storage attached to servers or shared by workspaces.

Key fields: `id`, `name`, `display_name`, `owner_id`, `visibility`, `size_bytes`,
`max_size_bytes`, `status`, `last_mounted_at`, `description`, `labels`,
`created_at`, `updated_at`.

`visibility` is `private`, `workspace`, or `public`; `labels` is JSONB and keeps
the home-volume marker after a server is deleted.

## SharedWorkspace

A group-owned workspace with members, invitations, and one or more volumes.
`SharedWorkspace` has `id`, `name`, `description`, `owner_id`, `is_active`,
timestamps, and relationships to `WorkspaceMember`, `WorkspaceInvitation`,
`WorkspaceVolume`, and plan access. `WorkspaceVolume` associates a workspace and
volume with a `read_only`/`read_write` role.

## CreditTransaction

Immutable NUKE ledger entry, range-partitioned by `created_at`.

Key fields: `id`, `user_id`, `amount`, `balance_after`, `type`, `description`,
`server_id`, `plan_id`, `actor_id`, `meta`, `created_at`.

`meta` is the JSONB metadata field; there is no `timestamp` or `metadata`
column.

## Credit Request

A user's request for credits, reviewed by an admin. At most one open
(`pending`/`needs_info`) request per user, enforced by a partial unique
index. Approving a `top_up` request grants credits as an `admin_grant`
ledger transaction tagged `source="credit_request"` in metadata; approving
an `allowance` request sets the user's base `daily_allowance` instead (no
ledger entry). Open requests past 24h trigger hourly reviewer reminders
(throttled to one per request per 24h).

Key fields: `id`, `user_id`, `amount`, `reason`, `request_type`, `status`,
`reviewed_by`, `review_note`, `granted_amount`, `transaction_id`, `created_at`,
`reviewed_at`. `transaction_id` is a plain column because the ledger is
partitioned and cannot be referenced by a foreign key.

Discussion between requester and reviewers lives in
`credit_request_messages` (`request_id`, nullable `author_id`, `body`,
`is_internal`, `created_at`). Internal notes are hidden from the requester.

## ActivityLog

Immutable audit record, range-partitioned by `created_at`.

Key fields: `id`, `actor_id`, `action`, `target_type`, `target_id`, `details`,
`before_state`, `after_state`, `request_id`, `ip_address`, `user_agent`,
`created_at`. There is no separate `AuditLog` table or actor username/role
column; projections join the actor when needed.

## Durable launch workflow

### ServerLaunchOperation

Immutable action intent plus a fenced executor state for a stable server.
Fields include `server_id`, `owner_id`, `action`, `state`, `fencing_token`,
`revision_id`, `request_payload`, `mounts`, `previous_mounts`, `gpu_devices`,
`username`, `environment_slug`, `resources`, `generation`, previous runtime
identity, `executor_id`, `heartbeat_at`, reason code, and timestamps. A partial
unique index allows only one `prepared`/`executing`/`uncertain` operation per
server. A partial recovery-scan index on
`(COALESCE(heartbeat_at, created_at), id)` for the active states keeps the
bounded oldest-first reconciliation query index-backed. Only `state`,
`reason_code`, `updated_at`, `finished_at`, `executor_id` and `heartbeat_at` are
mutable.

### ServerQueue

Owner-scoped waiting request. Status values are `pending`, `scheduled`,
`starting`, `started`, `failed`, and `cancelled`; a partial unique index keeps
one active request per owner/name. Durable fields include `request_payload`,
`request_version`, `plan_snapshot`, `revision_id`, `requested_gpu`, `expires_at`,
`claimed_at`, `claim_token`, `server_id`, `reason_code`, and timestamps. A
`starting` row is resolved against its linked create operation; an orphan is
cancelled only after runtime absence is proved from the recorded container ID,
server label, or deterministic launch name. Ambiguous cases stay `starting` with
`recovery_required`.

### EnvironmentRevision

Approved immutable environment fingerprint. Fields: `template_id`,
`fingerprint`, `template_fingerprint`, `portable_fingerprint`,
`configuration`, `runtime_identity`, `toolchain_identity`, `revoked`,
`created_at`. Only `revoked` may change after creation.

Active approval uniqueness is `(template_id, fingerprint) WHERE revoked = false`
(`uq_environment_revisions_active_fingerprint`), so revoking a revision and
verifying the same configuration again creates a new active row while revoked
history remains. `portable_fingerprint` has its own index
(`ix_environment_revisions_portable_fingerprint`) and is populated only for
registry-verified, portable configurations; local-only revisions keep it `NULL`.
It hashes normalized template configuration plus the verified platform manifest
digests and OS/architecture/variant, excluding tags, references, local image IDs,
environment values, host paths, database IDs and timestamps. Cross-install
manifest import matches active revisions by this fingerprint; local-only
manifests keep strict local revision matching.

### ServerLaunchIntent

Immutable provisioning intent committed before external launch work. Primary
key `server_id`; fields include `owner_id`, `revision_id`, `request_payload`,
`mounts`, `gpu_devices`, `environment_slug`, `username`, `queue_id`,
`claim_token`, `created_at`.

### ServerLaunchRecord

Append-only verified launch generation. Fields: `id`, `server_id`, `user_id`,
`revision_id`, `generation`, `manifest`, `actual_runtime_identity`,
`actual_toolchain_identity`, `created_at`. `(server_id, generation)` is unique.

### WorkerHeartbeat

Process-lifetime executor registry used by recovery inspection. The primary key
is `executor_id`; fields include `hostname`, `container_id`,
`container_started_at`, `pid`, `process_start_time`, `single_process_container`,
`schema_version`, `state`, `heartbeat_at`, and timestamps. API uvicorn workers and
the Celery worker register; Celery Beat does not. A heartbeat row records a
process incarnation and its last observed liveness, not authority to take over its
work. A graceful marker is written only after in-flight work drains. Because
`docker restart` keeps the container ID, `container_started_at` distinguishes a
restarted incarnation.

### VolumeOperation

Durable writer/mount/backup/restore exclusion. Composite key
`(operation_id, volume_id)`; fields include `owner_id`, `kind`, `state`,
`fencing_token`, `helper_identity`, `reason_code`, and timestamps. A partial
unique index permits one exclusive backup, restore, or batch `job_writer`
operation per volume while it is `reserved`, `running`, or
`recovery_required`. The guard releases only after the claimant's termination is
proved.

### BatchJob and BatchJobLog

`batch_jobs` is the durable owner intent and execution journal for one
noninteractive command. Fields include `user_id`, `name`,
`idempotency_key_hash`, `request_fingerprint`, `revision_id`, `plan_id`,
`volume_id`, literal `argv`, `max_runtime_seconds`, `state`, `reason_code`,
queue/create/start/deadline/stop timestamps, immutable revision/plan/volume
snapshots, reservation fields (`reservation_active`, reserved CPU/memory/disk,
`volume_operation_id`, `volume_fencing_token`), observed runtime identity,
`executor_id`, `heartbeat_at`, `fencing_token`, terminal result fields,
`cleanup_state`/`cleanup_attempts`, log metadata, and zero-cost billing fields.

Indexes cover owner history `(user_id, created_at, id)`, unique owner idempotency
`(user_id, idempotency_key_hash)`, queued dispatch `(created_at, id)`, queued
expiry `(queue_expires_at, id)`, active recovery
`(state, heartbeat_at, id)`, and unreleased reservations
`(reserved_at, id) WHERE reservation_active`.

`batch_job_logs` has one row per job: `job_id` primary key, bounded `text`,
`encoding`, `truncated`, `size_bytes`, `captured_at`, and `expires_at`. Payloads
are capped by `BATCH_JOBS_LOG_TAIL_BYTES` and hidden by the API after
`expires_at`; this release has no background physical-purge job. See
[BATCH-JOBS.md](BATCH-JOBS.md) for the lifecycle and admission contract.

### VolumeBackup and VolumeRestore

`volume_backups` stores source metadata, archive format/checksum, logical and
reserved bytes, operation fence, helper identity, artifact path, expiry, status,
`executor_id`, `heartbeat_at`, and completion time. `volume_restores` pins a
backup and stores the new destination identity, quota/storage reservation,
fence, status, `executor_id`, `heartbeat_at`, and completion time. Restore rows
prevent artifact deletion and retention until terminal. Both tables use the same
partial recovery-scan index shape for `pending`/`in_progress`/
`recovery_required`, keeping the bounded oldest-first scan from reading terminal
history.

## Schema conventions

- Primary keys are UUIDs generated by the application with `uuid.uuid4()` unless
  a migration explicitly adds a server default.
- Range-partitioned tables by month: `activity_logs`, `server_metrics`,
  `request_metrics`, and `credit_transactions`. Each has a `DEFAULT` partition.
- JSON/JSONB columns store flexible data (`profile`, `preferences`, `security`,
  `meta`, workflow payloads and manifests).
- Audit and credit tables are append-only; application code does not update or
  delete rows.
- Foreign keys enforce referential integrity; deletion is generally restricted,
  cascaded for owned child rows, or set to null for optional references.
- Alembic revisions form exactly one head. Migration tests assert the single
  head, and mixed or branched heads are unsupported for deployment. The batch
  job additions extend the chain through `e2c7a9f4d6b1`.

## Related documents

- [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for how entities transition through states
- [BATCH-JOBS.md](BATCH-JOBS.md) for single-run batch-job lifecycle and admission
- [AUTH.md](AUTH.md) for user and role authorization details
- [operations/OPERATIONS.md](../operations/OPERATIONS.md) for database profiling and partition management
- `backend/app/models/` and `backend/alembic/versions/` for the complete schema
