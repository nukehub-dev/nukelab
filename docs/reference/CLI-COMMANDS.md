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
./nukelabctl logs [service] # Stream logs for a service (backend, frontend, postgres, redis, celery, ...)
```

### Development

```bash
./nukelabctl dev            # Start the development stack with hot reload
./nukelabctl dev start
./nukelabctl dev restart
./nukelabctl dev stop
./nukelabctl dev logs backend
```

The dev and production stacks use the same container names; only one may run at a time.

### Build

```bash
./nukelabctl build          # Rebuild all service images
./nukelabctl build backend
./nukelabctl build frontend
./nukelabctl build auth-sidecar
```

### Overlays

```bash
./nukelabctl start --overlay compose.monitoring.yml
./nukelabctl start --overlay compose.pgbouncer.yml
```

You can also set `COMPOSE_OVERLAYS` in `.env` to always include overlays.

### Database operations

```bash
./nukelabctl exec backend alembic upgrade head
./nukelabctl exec backend python scripts/db_profiler.py table-sizes
./nukelabctl exec backend python scripts/tune_autovacuum.py --dry-run
```

### Backup and restore

```bash
./nukelabctl backup
./nukelabctl restore backups/nukelab_backup_YYYYMMDD_HHMMSS.sql
```

### Testing and verification

```bash
./nukelabctl lint all              # ruff + eslint/prettier + shellcheck/shfmt
./nukelabctl lint all --fix        # Auto-fix where supported
./nukelabctl test all              # Frontend unit tests + backend pytest
./nukelabctl test backend tests/api/servers/test_servers.py -x -v
./nukelabctl selftest              # nukelabctl sanity check
```

### Security

```bash
./nukelabctl security
./nukelabctl verify-hardening <container_name>
./nukelabctl security --check-base-images
./nukelabctl security --signed-commits
./nukelabctl security --sbom
```

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
