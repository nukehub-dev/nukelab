# NukeLab

Multi-user scientific computing platform with granular RBAC, real-time
monitoring, credit-based resource management, and dynamic container orchestration.

## Highlights

- **Role-based access control** with a permission matrix and per-role customization
- **Dynamic user environments** via admin-defined Docker image templates
- **Resource plans** that enforce CPU, memory, and disk limits per server
- **NUKE credit system** for fair resource allocation and auto-billing
- **Crash-safe recovery** with worker/operation heartbeats, proof-backed reconciliation, admin visibility, and no time-based takeover
- **Registry-verified environments** with exact platform-digest identity, optional digest pulls, and portable fingerprints
- **Real-time metrics** through WebSockets with optional Prometheus + Grafana + Jaeger
- **Security-first defaults**: hardened containers, CSRF protection, strict CORS, security headers, and audit logging
- **Supply-chain checks**: strict base-image pinning, weekly digest-drift review, and release SBOM/provenance attestations
- **Container flexibility**: runs on Docker or Podman, with Traefik v3 as the reverse proxy

## Quick Start

Requires Docker or Podman, compose, and Git. The hot-reload development stack
additionally needs Node.js 24+ and npm; run `./nukelabctl install frontend`
before `./nukelabctl dev`.

```bash
git clone https://github.com/nukehub-dev/nukelab.git
cd nukelab
cp .env.example .env.development
./nukelabctl start
```

After start:

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:8080` |
| API | `http://localhost:8080/api` |
| API docs | `http://localhost:8080/api/docs` |

Default development login: `admin` / `admin123`.

On a fresh install, sign in as an administrator and open **Administration →
Setup** (`/admin/setup`) to publish an active public environment and make at
least one plan available to users before deploying.

For hot-reload development:

```bash
./nukelabctl install frontend
./nukelabctl dev
```

## Architecture at a Glance

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/architecture-light.svg">
  <img src="docs/assets/architecture-light.svg" alt="NukeLab architecture: browser traffic reaches Traefik, which routes to the React SPA, FastAPI backend, and NukeIDE containers. The backend and Celery workers use PostgreSQL, Redis, and the container driver, while an optional observability stack covers the platform.">
</picture>

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) for the full
system overview and [docs/architecture/COMPONENTS.md](docs/architecture/COMPONENTS.md)
for component responsibilities.

## Documentation

| Topic | Location |
| --- | --- |
| System overview and request flows | [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) |
| Component responsibilities | [docs/architecture/COMPONENTS.md](docs/architecture/COMPONENTS.md) |
| Authentication and authorization | [docs/architecture/AUTH.md](docs/architecture/AUTH.md) |
| Queue, lifecycle, provenance, recovery and recreation | [docs/architecture/SERVER-LIFECYCLE.md](docs/architecture/SERVER-LIFECYCLE.md) |
| Core data model | [docs/architecture/DATA-MODEL.md](docs/architecture/DATA-MODEL.md) |
| Local development | [docs/development/LOCAL-DEV.md](docs/development/LOCAL-DEV.md) |
| Contributing guidelines | [docs/development/CONTRIBUTING.md](docs/development/CONTRIBUTING.md) |
| Operations (first-run setup, recovery, upgrades, DB, backups, supply chain) | [docs/operations/OPERATIONS.md](docs/operations/OPERATIONS.md) |
| Production deployment | [docs/operations/PRODUCTION-DEPLOYMENT.md](docs/operations/PRODUCTION-DEPLOYMENT.md) |
| Database and private-volume backup/restore | [docs/operations/BACKUP-RESTORE.md](docs/operations/BACKUP-RESTORE.md) |
| Monitoring and observability | [docs/architecture/MONITORING.md](docs/architecture/MONITORING.md) |
| Security test plans and findings | [docs/security/](docs/security/) |
| Environment variables | [docs/reference/ENV-VARS.md](docs/reference/ENV-VARS.md) |
| CLI command reference | [docs/reference/CLI-COMMANDS.md](docs/reference/CLI-COMMANDS.md) |

Start with [docs/README.md](docs/README.md) for a guided index.

## Management Commands

```bash
./nukelabctl start          # Start all services
./nukelabctl stop           # Stop all services
./nukelabctl restart        # Restart all services
./nukelabctl dev            # Start development stack with hot reload
./nukelabctl build          # Rebuild containers
./nukelabctl logs [service] # View logs for a service
./nukelabctl status         # Show running containers
```

See [docs/reference/CLI-COMMANDS.md](docs/reference/CLI-COMMANDS.md) for the full
command reference.

## Technology Stack

- **Reverse Proxy**: Traefik v3
- **Frontend**: Vite + React 19 SPA, Tailwind CSS, TanStack Router, TanStack Query
- **Backend**: FastAPI (Python 3.13), Pydantic v2, SQLAlchemy 2, asyncpg
- **Database**: PostgreSQL 17 with partitioned time-series tables
- **Cache / Queue**: Redis (sessions, pub/sub, Celery broker, caching)
- **Task Queue**: Celery with Celery Beat
- **Observability**: Prometheus, Grafana, Alertmanager, Jaeger, OpenTelemetry
- **Container Engine**: Docker or Podman

## API

The REST API is documented automatically at `/api/docs` and `/api/openapi.json`
when the backend is running.

## License

[BSD-2-Clause](LICENSE)
