# NukeLab CLI Reference

`nukelabctl` is the top-level management script for the NukeLab platform. It auto-detects Docker vs Podman, manages compose overlays, and tracks per-stack state.

## Getting help

```bash
./nukelabctl --help
./nukelabctl <command> --help
```

The built-in help is the authoritative source for all available commands and flags.

## Common commands

### Lifecycle

```bash
./nukelabctl start          # Start the production stack
./nukelabctl stop           # Stop the production stack
./nukelabctl restart        # Restart the production stack
./nukelabctl status         # Show running containers
./nukelabctl logs [service] # Stream logs (backend, frontend, postgres, redis, celery-worker, celery-beat, ...)
```

`start` accepts `backend`, `frontend`, or `all`, plus `--no-build`,
`--no-wait`, and `--overlay <file>`.

### Development

```bash
./nukelabctl dev            # Start the development stack with hot reload
./nukelabctl dev start
./nukelabctl dev restart
./nukelabctl dev stop
./nukelabctl dev logs backend
```

The dev and production stacks use the same container names; only one may run at a time.

### Build, update and deploy

```bash
./nukelabctl build          # Rebuild all service images
./nukelabctl build backend
./nukelabctl build frontend
./nukelabctl build env base   # builds the auth sidecar, then base environment images
./nukelabctl update         # Pull images and rebuild/re-pull; run restart to apply
./nukelabctl update --cache # Reuse layer cache
./nukelabctl pull           # Pull base images used by compose services
./nukelabctl cache-toolchain <image>
```

Pinning `NUKELAB_VERSION` or `NUKELAB_IMAGE_TAG` switches `start` and
`update` to pulling the tagged `ghcr.io/nukehub-dev/nukelab-backend` and
`-frontend` images. `update --build` forces a source rebuild in pull mode.

### Maintenance

```bash
./nukelabctl clean          # Remove stopped containers, dangling images/volumes, build cache
./nukelabctl remove         # Remove containers but keep volumes and data
./nukelabctl reset          # ⚠️ Delete all stack data, containers, and volumes
```

`clean` and `reset` ask for confirmation unless `--yes` is supplied.

### Environment files

```bash
./nukelabctl check-env              # Compare the active env file with .env.example
./nukelabctl check-env --all        # Check .env and .env.development
./nukelabctl check-env --changed    # Also report values that differ from defaults
./nukelabctl sync-env               # Non-destructively add missing keys
./nukelabctl sync-env --dry-run
```

`sync-env` never overwrites existing keys or secrets.

### Shell, install and overlays

```bash
./nukelabctl shell backend
./nukelabctl exec backend python -v
./nukelabctl install frontend
./nukelabctl start --overlay compose.monitoring.yml
./nukelabctl start --overlay compose.pgbouncer.yml
```

You can also set `COMPOSE_OVERLAYS` in `.env` to always include overlays.

### Database operations

```bash
./nukelabctl db-migrate     # Apply Alembic migrations with a pre-migration snapshot
./nukelabctl db-migrate --no-backup   # Skip the snapshot only when you already have one
./nukelabctl db-shell       # Open a PostgreSQL shell
./nukelabctl exec backend python scripts/db_profiler.py table-sizes
./nukelabctl exec backend python scripts/tune_autovacuum.py --dry-run
```

### Backup and restore

```bash
./nukelabctl backup
./nukelabctl restore backups/nukelab_backup_YYYYMMDD_HHMMSS.sql   # asks for confirmation; --yes skips
./nukelabctl restore --yes --stamp <revision> backups/pre-migrate-<version>-<revision>-<timestamp>.dump
```

Use `--stamp <revision>` for a pre-migration rollback so the restored schema is
stamped with the previous release's Alembic revision instead of `head`.

### Testing and verification

```bash
./nukelabctl lint all              # ruff + eslint/prettier + shellcheck/shfmt + markdown
./nukelabctl lint all --fix        # Auto-fix where supported
./nukelabctl test all              # Frontend unit tests + backend pytest
./nukelabctl test backend tests/api/servers/test_servers.py -x -v
./nukelabctl e2e                   # Playwright against a running backend
./nukelabctl selftest              # nukelabctl sanity check
```

`e2e` forwards its arguments to `npx playwright test`, for example
`./nukelabctl e2e --grep login`. The disposable external stack is managed by
`scripts/ci/e2e-stack.sh` (`build [--workspace]`, `start`, `wait`, `stop`,
`fixtures`); set `E2E_EXTERNAL_SERVER=1` and `BASE_URL` when running against
it.

### Security

```bash
./nukelabctl security
./nukelabctl verify-hardening <container_name>
./nukelabctl security --check-base-images
./nukelabctl security --signed-commits
./nukelabctl security --sbom
./nukelabctl security --backend-only
./nukelabctl security --frontend-only
./nukelabctl security --no-trivy
./nukelabctl security --with-dev
./nukelabctl security --no-fail-on-high
./nukelabctl security --bandit-severity=medium
```

### User authentication keys

```bash
./nukelabctl init-user-auth-keys       # Generate the initial Ed25519 key pair
./nukelabctl rotate-user-auth-key      # Rotate while retaining retired keys
./nukelabctl cleanup-user-auth-keys    # Remove expired retired keys
```

Production requires `init-user-auth-keys` before the backend starts.

### Diagnostics

```bash
./nukelabctl doctor          # Check host readiness (tolerates a stopped stack)
./nukelabctl doctor --post-upgrade
./nukelabctl doctor --post-upgrade --expected-version 2.4.0
./nukelabctl version         # Show platform and engine versions
./nukelabctl install-completion
```

`doctor --post-upgrade` verifies a running deployment without changing it:
required service containers, public API health and release version, running
service image identity, database Alembic head compatibility, Celery worker
heartbeat and Beat presence, unresolved recovery rows, and optional batch-job
tables. It reports expected and observed values and exits `1` when a required
check fails; warnings do not fail the run. `--expected-version` overrides the
version resolved from `NUKELAB_VERSION`, `VERSION`, or `git describe`. Run
`./nukelabctl doctor --help` for the complete check list.

### Load testing

```bash
./nukelabctl loadtest
```

## Command locations

- `nukelabctl` — top-level dispatcher
- `scripts/lib.sh` — shared helpers
- `scripts/manage.d/*.sh` — one file per command

## Related documents

- [development/LOCAL-DEV.md](../development/LOCAL-DEV.md) for development-specific usage
- [operations/OPERATIONS.md](../operations/OPERATIONS.md) for database and operational commands
- [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for production deployment commands
- [operations/BACKUP-RESTORE.md](../operations/BACKUP-RESTORE.md) for backup and restore details
