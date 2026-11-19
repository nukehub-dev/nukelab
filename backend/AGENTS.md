# Backend

## Purpose

Python FastAPI backend for the NukeLab platform: REST API, WebSocket events, business logic, SQLAlchemy models, Alembic migrations, Celery background tasks, and container orchestration via the Docker SDK.

## Ownership

All files under `backend/` except generated artifacts (`.venv-dev`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `htmlcov`, `logs`).

## Local Contracts

- Python 3.13; formatting and linting configured in `pyproject.toml`.
- `app/main.py` is the ASGI entry point.
- `app/version.py` holds the static fallback `__version__` — permanently `0.0.0-dev`, never bumped. The effective runtime version is `settings.app_version` (`app/config.py`): the `APP_VERSION` env var wins, with empty/unset falling back to the literal. `APP_VERSION` is injected as a Docker build arg both by CI (the image tag) and by local compose builds (`NUKELAB_VERSION` exported by `nukelabctl`). `main.py` and `app/api/health.py` read `settings.app_version` — never hardcode the version string.
- `app/api/` owns route definitions; `app/services/` owns business logic; `app/models/` owns SQLAlchemy models; `app/db/` owns session/connection logic; `app/core/` owns cross-cutting utilities; `app/middleware/` owns ASGI middleware; `app/container/` owns container-runtime orchestration; `app/tasks.py` and `app/worker.py` own Celery.
- `app/container/` is a driver layer: `driver.py` defines the `ContainerDriver` ABC + `ContainerDriverError` (plain-data returns only — no runtime objects escape), `docker_driver.py` is the Docker/Podman implementation, `factory.py` selects the driver via `CONTAINER_RUNTIME` (default `docker`), `client.py` is a compatibility shim for legacy imports/test seams, and `spawner.py` (server lifecycle) talks only to driver methods. To add a runtime (e.g. Kubernetes): implement `ContainerDriver` (synthesizing the documented return shapes, e.g. Docker-stats for `get_container_stats`) and register it in `factory.py`. Container health is driver-level config, not image metadata: `docker_driver.py` injects a uniform `Healthcheck` (`/usr/local/bin/nukelab-healthcheck.sh`) into every create config, because OCI images drop Dockerfile `HEALTHCHECK` and Kubernetes ignores it — a k8s driver must translate the same definition into pod liveness/startup probes and surface failures as the same `State.Health.Status` shape `HealthCheckService` consumes. `spawner.py` performs two readiness probes before marking a server `running`: (1) the container's own `/health` endpoint over the Docker network alias, and (2) the public server path through the internal Traefik load balancer (`TRAEFIK_INTERNAL_URL`, default `http://traefik:80`) with a `healthy` body check. This ensures the browser-facing route exists before the frontend is told to redirect.
- Notifications: `app/services/notification_service.py` owns notification creation and delivery. Channels are `in_app`, `email`, `webhook`, and (when VAPID keys are configured) `push`. Push payloads are short previews only; dead subscriptions are removed on `404`/`410`. VAPID config and the `push_subscriptions` model live in `app/config.py` and `app/models/push_subscription.py`; pass `VAPID_*` env vars to both the `backend` and `celery-worker` containers.
- `app/api/search.py` — grouped, permission-scoped search at `/api/search/`; optional `group` query parameter scopes the response to a single group; groups the user lacks read permission for are omitted from the response (never 403).
- `app/api/tokens.py` owns `VALID_TOKEN_SCOPES`, the source of truth for API-token scopes; the frontend `AVAILABLE_SCOPES` in `frontend/src/components/settings/tokens-page.tsx` must stay in sync (unknown scopes are rejected with 422).
- `app/services/gpu_allocator.py` owns exclusive GPU device reservations (table `gpu_allocations`, active only when `GPU_DEVICES` lists CDI device names); every code path that stops or deletes a server must release its devices, and every GPU spawn path must allocate first.
- `alembic/` owns database migrations; use Alembic commands to generate and test upgrades/downgrades.
- `tests/` mirrors the `app/` structure; security regressions go in `tests/security/`.
- `services/admission_service.py` owns transaction admission locking: callers use Read Committed, acquire the lock before fresh accounting queries, flush reservations without internal commits, then commit before runtime I/O. It does not reserve resources by itself.
- `services/server_launch_service.py` owns the clean session and transaction boundaries for normalized direct/deferred launch orchestration. `reserve()` performs current policy checks and commits the stable starting server, immutable `ServerLaunchIntent`, GPU allocation and mount intents before runtime I/O; `provision()` updates that same server and records verified runtime provenance. Fresh-session recovery reloads the exact revision/request/mount intent; uncertain failures retain reservations for reconciliation. Reserved runtime names derive from the server UUID. Creation APIs and queue workers select this boundary; logout-triggered stops also use verified termination; existing-server actions use `server_lifecycle_service.py` and verified stop/delete use `server_termination_service.py`. A newly created private volume selected for a launch is marked `initialize_for_server` and gets one-time mount-root permission setup; volumes that already hold data or have prior attachments are not relabeled or chmodded.
- `server_operation_service.py` owns immutable per-action intent and fenced executor claims. A partial unique index permits only one prepared/executing/uncertain operation per server. Uncertain outcomes have no TTL takeover; stop/delete and resource release require runtime proof. Restarts retain the larger old/new reservation until the predecessor is verified gone. Status reads apply observations only if container identity, row version and active-operation checks remain authoritative under admission.
- Quota/GPU helpers preserve their compatibility `commit=True` default. Admission callers use `commit=False`; quota recomputation counts persisted starting/stopping reservations exactly once and skips destructive GPU reconciliation. `include_gpu_pool=False` defers physical scarcity to admission while retaining user GPU quota enforcement.
- Seeded plans remain editable, but the catalog cannot be made un-deployable: `services/plan_service.py` refuses update/deactivate/delete operations that would leave no active plan or no active plan available to the `user` role (409). Small/Medium/Large seed with `visible_to_roles=["user"]`; XLarge remains admin-only. The seeder only creates missing slugs and never overwrites admin edits.
- Admin bulk server lifecycle requires server-write authority plus a cross-user reason, and must run the shared cross-user audit/notification path before mutation. `ADMIN_ACCESS` alone is insufficient; regression coverage lives in `tests/security/test_admin_bulk_authorization.py`.
- `services/operation_runner.py` owns long-operation loops and task-local DB/driver resources. Deadlines join cooperative cancellation; uncertain external outcomes retain reservations until runtime reconciliation. Runtime-capable queue, lifecycle enforcement, scheduling and health tasks use this boundary with loop-owned fresh sessions/drivers.
- Queue request/claim primitives live in `services/server_queue_service.py` and typed DTOs in `schemas/server_queue.py`. `server_queue_dispatch_service.py` supplies bounded first-fit dispatch with a durable rotating cursor and an operation-owned synchronous runner selected by the scheduled task. The registered queue router exposes capability discovery and owner-scoped list/detail/pending cancellation; cancellation and claims share admission serialization.
- Approved revision/provenance primitives require current-template authorization callbacks, immutable image selection, and observed launch identity checks. Public manifests contain environment-variable names only; repository digest metadata alone never establishes portability. Launch/recreation selects captured revisions and records successive verified generations; legacy servers missing plan/environment selection can only resume an existing verified non-exclusive-GPU container. An unrecorded server with a valid selection captures its first verified revision on recreation; this does not backfill historic proof. The registered `api/server_provenance.py` and `services/server_recreation_service.py` expose saved history/export and approved recreation; registry portability remains separate work.
- Provenance history/export require server read permission and `servers:read`; foreign history retains JWT, reason and audit checks. Recreation source launch IDs are owner-only and new servers belong to the actor. Preview discloses saved metadata and requires separate read/write permission checks plus both read/manage scopes; final recreation requires write/manage. History stays readable after revision revocation, while preview/final submission recheck current approval. Eligibility never guarantees capacity or artifact availability.
- Recreation accepts a bounded strict manifest matching an existing approved revision or an owned launch, a current plan, a new name and explicit volume choices. Bindings preserve the preview's normalized ordered paths/modes; no source volume IDs, environment values or historical resource entitlements are imported. `submit_pinned()` verifies exact local image identity/platform outside admission before reserving; absent artifacts never fall back to mutable tags.
- Shared mount validation rejects user-data overlap with system security paths and the selected approved toolchain roots, including ancestor/descendant overlaps. Preview and final launch use the same validator; historical exports remain readable when an old destination is no longer supported.
- Home mount history (`was_home_volume`) survives server edits/deletion so sharing warnings remain visible; launch/resume records `last_mounted_at`, while offline selection changes preserve the home marker without inventing runtime use.
- Volume intents use admission serialization followed by sorted volume locks and refreshed reads. `volume_mutation_service.py` guards file deletion, metadata and workspace sharing changes; launch mount intents participate in the same exclusion. Runtime deletion requires verified absence; unknown outcomes retain the guard. User deletion requires explicit resource cleanup.
- `volume_backup_service.py` owns owner-only offline private-volume recovery admission, bounded storage reservations, immutable operation identities, retention and restore pins. `volume_recovery_runtime.py` owns fixed hardened helper mounts, all-container attachment checks and termination/cleanup proof. API/worker storage paths must refer to the same operator-owned private bind; missing storage/helper disables admission without breaking unrelated startup. No TTL takeover or automatic source stop is permitted. Trusted compose services (`backend`, `celery-worker`, `celery-beat`, `backend-test`) may bind the private storage root; their parent-path bind is not a user attachment and must not block volume detachment or artifact cleanup.
- Restore always allocates a new quota-reserved volume. Only verified complete destinations become active; failed destinations remain inaccessible until explicitly deleted. Archive extraction accepts relative symlinks without parent components and hardlinks to earlier regular files; runtime limits and termination proof supplement archive validation. Artifact metadata stays readable when recovery is disabled, and completed copies survive source deletion.

## Work Guidance

### Project structure

- `app/api/` — API routers mounted under `/api`. Group endpoints by resource (e.g., `servers.py`, `users.py`).
- `app/services/` — business logic called by API routes and tasks. Keep routes thin; put logic here.
- `app/models/` — SQLAlchemy ORM models. One model per file or one file per feature as the project already does.
- `app/schemas/` — Pydantic request/response models shared between API and services.
- `app/db/` — database session factory, engine configuration, and connection helpers.
- `app/dependencies.py` — FastAPI dependency injection (DB sessions, auth, permissions).
- `app/core/permissions.py` — canonical permission string constants (`Permission.*`).
- `app/core/roles.py` — role-to-permission matrix (`ROLE_PERMISSIONS`) and runtime loading/saving of overrides from the config store.
- `app/core/security.py` — permission evaluation helpers (`has_permission`, `has_any_permission`, `has_all_permissions`).
- `app/core/` — logging, config, exceptions, security utilities.
- `app/container/` — Docker SDK client and container lifecycle operations.
- `app/tasks.py` / `app/worker.py` — Celery task definitions and worker entry point.

### Adding an endpoint

1. Define Pydantic request/response schemas in `app/schemas/`.
2. Add the route handler in the appropriate `app/api/` router.
3. Implement business logic in `app/services/`. Inject the DB session via `app/dependencies.py`.
4. Add tests in `tests/api/` or `tests/services/` mirroring the source path.
5. Update OpenAPI-generated docs if the project exposes them.

### Database changes

- Update SQLAlchemy models in `app/models/` first.
- Generate a migration with `alembic revision --autogenerate -m "description"` inside the backend container or host venv.
- Review the generated migration before committing; autogenerated scripts can miss renames and complex changes.
- Test upgrade and downgrade locally: `alembic upgrade head && alembic downgrade -1`.
- Migrations must be reversible and tested against the current schema.
- **Expand-contract for destructive changes:** split drops, renames, and removals across two releases so the previous release's code still runs on the new schema. For example, release N adds the replacement column and dual-writes; release N+1 removes the old column once no deployed image references it.

### Schema-compatibility guard

`app/db/schema_guard.py` protects against the pull-deploy rollback hazard where
an older backend image boots against a database that already ran newer Alembic
migrations.

- `check_schema_compatibility(engine, script_dir_path)` reads the DB's
  `alembic_version` revision(s), walks the local Alembic `ScriptDirectory`, and
  reports whether every DB revision is known to the running image.
- `run_schema_guard(engine, script_dir_path, mode, app_env)` applies the
  configured policy and raises `RuntimeError` when a rollback hazard is detected
  in a refusing mode.
- The guard is controlled by the `DB_SCHEMA_GUARD` setting (`app/config.py`):
  - `auto` (default): refuse to start in production, warn in other environments.
  - `enforce`: always refuse.
  - `off`: disabled.
- If the database is unreachable, the guard logs a warning and does not block
  startup, so DB outages do not become a new failure mode.

### Background tasks

- Use Celery for work that can run asynchronously (e.g., container metrics collection, long-running provisioning).
- Define tasks in `app/tasks.py`; call them with `.delay()` or `.apply_async()` from services or routes.
- Keep tasks idempotent where possible and handle retries explicitly.
- `shutdown_idle_servers` decides idleness from `Server.last_activity` merged with the proxied-traffic timestamp each container's auth sidecar reports via `GET http://srv-<server_id[:8]>:8080/activity` (`_fetch_sidecar_activity`). Probe failures must fall back to the DB timestamp and never block shutdown. `last_activity` writers: spawn/start/restart/access-token paths, `POST /servers/:id/activity` (interaction-gated SPA heartbeat), the sidecar merge, and — indirectly — the nuke-ide `NukeLabActivityContribution` heartbeat that traverses the sidecar while the user works in the IDE.

### Docker orchestration

- Use the `ContainerDriver` methods from `app/container/` (via the factory or the `client.py` shim), not raw Docker SDK/aiodocker calls scattered in routes and services. Only `docker_driver.py` may touch aiodocker.
- Container operations must respect `CONTAINER_HARDENING_ENABLED` and run spawned containers as non-root with dropped capabilities.
- The `celery-worker` container runs queue dispatch, scheduled start/stop, health restarts and lifecycle enforcement, so it must receive the same runtime/security env as `backend`: `CONTAINER_HARDENING_ENABLED`, `CONTAINER_RUNTIME`, server-auth settings, `APP_URL`/`PUBLIC_URL`, `DEV_MODE`/`APP_ENV`, GPU and resource-pool settings. A missing value silently changes spawned-container behavior.
- Read-only rootfs tmpfs includes `/home` so a server that selects only non-home data volumes can still initialize its runtime home. A mounted home volume remains the persistent location; otherwise the runtime home is ephemeral.
- Runtime composition has two explicit paths. Legacy `spawn()` callers use tag-keyed toolchain caches with stamp invalidation and degraded fallback. The reserved path supplies `resolved_images`, uses only approved immutable local IDs, requires readiness/toolchain success, and refuses destructive runtime adoption or missing existing data volumes. It accepts only service-resolved named mounts; it does not change permissions on existing or read-only data mounts.
- `ContainerDriver.resolve_image()` returns plain local identity/platform data; RepoDigests stay unverified. `prepare_immutable_toolchain_volume()` supports one approved root and uses identity/platform/layout-keyed caches. Existing incomplete/mismatched caches fail closed without repopulation; uncertain helper termination retains its atomic lock, with no TTL takeover. New scientific cache versions leave live legacy caches intact.
- Mutating driver methods (`stop_container`, `delete_container`, `start_container`) raise `ContainerDriverError` on runtime failure — never swallow. `spawner.stop/start/delete` map that to a `bool` (treating 304/404 as the already-achieved end state) and `spawner.get_status` returns `"unknown"` on lookup failure. Stop/delete paths must never mark a server `stopped` or remove its DB row on `False`/`"unknown"` — the container may still be running (DB status must stay consistent with live containers). Log, surface the error (API: 503; bulk: per-item failure), or skip and let the next task cycle retry.

### Authentication and authorization

- Reuse existing dependency callables in `app/dependencies.py` for current-user and permission checks.
- Do not implement ad-hoc authorization inside service functions unless unavoidable.

### Role-based access control (RBAC)

NukeLab uses role-based access control with dynamic permission overrides. The canonical permission strings live in `app/core/permissions.py` as the `Permission` class. The default role-to-permission mapping lives in `app/core/roles.py` as `ROLE_PERMISSIONS` and is loaded from the config store at startup so administrators can override it at runtime via `/admin/permissions`.

- **Source of truth for permission strings**: `app/core/permissions.py`. Add new permissions there first, then include them in `Permission.all_permissions()`.
- **Source of truth for default role grants**: `app/core/roles.py`. Each role lists explicit grants; higher-privilege permissions do **not** automatically imply lower ones unless `_expand_permissions` expands them (e.g., `servers:read_all` implies `servers:read_own`).
- **Runtime overrides**: stored in the config store as `role_permissions` and loaded by `load_role_permissions_from_db()` during startup. Edits from the admin UI update `ROLE_PERMISSIONS` and call `save_role_permissions_to_db()`.

#### Protecting a route

Use dependency injection; never rely on caller-provided role/permission values:

```python
from fastapi import Depends
from app.dependencies import require_permissions, require_admin, PermissionChecker
from app.core.permissions import Permission

# Require a single permission
@router.get("/users")
async def list_users(current_user: User = Depends(require_permissions(Permission.USERS_READ))):
    ...

# Require admin dashboard access
@router.get("/admin/stats")
async def admin_stats(current_user: User = Depends(require_admin)):
    ...

# Complex resource-level check
@router.get("/servers/{server_id}")
async def get_server(
    server_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    server = await server_service.get_server(server_id, db)
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL])
    if not checker.can_access_resource(str(server.user_id)):
        raise HTTPException(status_code=403, detail="Access denied")
    return server
```

Prefer `require_permissions` for simple endpoint-level checks. Use `PermissionChecker` when you need resource ownership checks (`can_access_resource`), `require_all`, or multiple conditional branches.

#### Adding or changing permissions

1. Add the new constant to `app/core/permissions.py` and `Permission.all_permissions()`.
2. Assign it to the appropriate default roles in `app/core/roles.py`. Consider whether `_expand_permissions` needs to know about any implication rules.
3. Use it in `app/dependencies.py` (add a convenience alias if it will be reused) or inline in route handlers.
4. Expose it to the frontend by ensuring it is included in API responses (e.g., user profile, `/admin/permissions` matrix).
5. Add corresponding regression tests under `tests/core/test_dependencies.py` and `tests/security/` if the permission guards sensitive functionality.

#### Important rules

- The backend is the ultimate authority: every protected API call must be authorized server-side, even if the frontend also hides UI elements.
- Do not check `user.role == "admin"` directly outside of `app/core/roles.py` and `app/core/security.py`. Use `has_permission` or `PermissionChecker` so dynamic overrides are respected.
- `super_admin` is represented by `Permission.ALL` (`*`) and bypasses all permission checks.

### Logging and configuration

- Prefer structured logging via `app/core/logging`; avoid `print()` in production code.
- Environment config lives in `app/config.py`; read values from there, not directly from `os.environ`.

### Testing

- Run backend tests with `./nukelabctl test backend [pytest args]`.
- Volume API regressions live in `tests/api/volumes/` and must remain tracked; the root runtime-data ignore rule is `/volumes/`, never an unanchored `volumes/`.
- Add regression tests for every confirmed security finding under `tests/security/`.
- Use the existing fixtures in `conftest.py` for DB sessions, test clients, and Celery config.
- Native CPU-mask passthrough tests compare the preloaded binary with an unpreloaded baseline under the same user and container; do not assume write-mode `/proc/stat` opens fail for root. Compare open success/failure, errno, and descriptor access mode without writing to procfs.
- Real container/image fixture tests are opt-in with `--run-container-integration`; they use unique ownership labels and remove only their own resources. Run against an isolated local/CI test daemon.
- Security tests that mock the Docker client should run with `--confcutdir=tests/security` to avoid the root Postgres/Redis fixtures.
- New lifecycle/queue/recovery suites:
  - `tests/services/test_server_queue_service.py`, `test_server_queue_dispatch_service.py`, `test_queue_scan_cursor.py`, `tests/api/test_server_queue.py`;
  - `tests/services/test_environment_provenance*.py`, `tests/api/servers/test_server_provenance.py`, `tests/security/test_provenance_recreation.py`;
  - `tests/services/test_volume_backup_service.py`, `tests/security/test_volume_recovery_*.py`, `tests/tasks/test_volume_recovery_workers.py`.
- Run `./nukelabctl test all` for the full suite; scope a suite with
  `./nukelabctl test backend <path> -q`. Do not lower the coverage floor.

### Common pitfalls

- Keep middleware concerns in `app/middleware/`; do not inline ASGI logic in `main.py`.
- Do not leak Docker SDK exceptions directly to API clients; translate them to HTTP exceptions.
- Avoid N+1 queries; use `selectinload` or joined loads when returning relationships.

## Verification

```bash
./nukelabctl lint backend
./nukelabctl test backend
```

- Coverage floor is **94%** (`--cov-fail-under=94` in `test backend --coverage`, run by CI). The suite currently sits at ~96%; keep it at or above the floor — raise the floor, never lower it.

## Child NAD Index

- None
