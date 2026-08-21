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

## Work Guidance

### Project structure

- `app/api/v1/` — versioned API routers. Group endpoints by resource (e.g., `servers.py`, `users.py`).
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
2. Add the route handler in the appropriate `app/api/v1/` router.
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
- Runtime composition: scientific toolchain images are mounted as shared read-only volumes into the workspace runtime container. `ContainerDriver.prepare_toolchain_volume()` populates the volume and returns the toolchain manifest; a k3s driver implements the same flow with an init container. Population is serialized across processes by a lock container (atomic name creation, stale locks force-removed after 15 min); a stamp file (`<target>/.nukelab-toolchain-stamp.json` with `image_id`/`repo_digests`) invalidates the volume when the local image changes, triggering a wipe + re-populate. Image IDs are compared by digest portion only, so stamps stay valid when `cache-toolchain` (CLI) and the backend (aiodocker) report different Id formats across engines. Helper containers run hardened (CapDrop ALL, no-new-privileges, read-only rootfs; populate re-adds only the caps `cp -a` needs). The spawner merges manifest `env_prepend` (PATH-family lists, prepended) and `env` (scalars, applied with `setdefault` so explicit vars win); toolchain failure is non-fatal but logged at error level as `TOOLCHAIN_DEGRADED`.
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
- Add regression tests for every confirmed security finding under `tests/security/`.
- Use the existing fixtures in `conftest.py` for DB sessions, test clients, and Celery config.
- Security tests that mock the Docker client should run with `--confcutdir=tests/security` to avoid the root Postgres/Redis fixtures.

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
