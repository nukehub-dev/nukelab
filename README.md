# NukeLab

Multi-user scientific computing platform with granular RBAC, real-time
monitoring, credit-based resource management, and dynamic container orchestration.

## Highlights

- **Role-based access control** with a permission matrix and per-role customization
- **Dynamic user environments** via admin-defined Docker image templates
- **Resource plans** that enforce CPU, memory, and disk limits per server
- **NUKE credit system** for fair resource allocation and auto-billing
- **Real-time metrics** through WebSockets with optional Prometheus + Grafana + Jaeger
- **Security-first defaults**: hardened containers, CSRF protection, strict CORS, security headers, and audit logging
- **Container flexibility**: runs on Docker or Podman, with Traefik v3 as the reverse proxy

## Quick Start

Requires Docker or Podman, compose, and Git.

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

For hot-reload development:

```bash
./nukelabctl dev
```

## Architecture at a Glance

```text
                              Traefik v3
                    ┌───────────┬───────────┐
                    │           │           │
               /*   │      /api/*    /user/{username}/*
                    │           │           │
                    ▼           ▼           ▼
              ┌─────────┐  ┌─────────┐  ┌─────────────────┐
              │  Vite   │  │ FastAPI │  │  NukeIDE user   │
              │  React  │  │ Backend │  │  containers     │
              │   SPA   │  │         │  │  (nginx + IDE)  │
              └────┬────┘  └────┬────┘  └─────────────────┘
                   │            │
                   └────────────┼────────────┐
                                ▼            ▼
                         ┌──────────┐   ┌──────────┐
                         │PostgreSQL│   │  Redis   │
                         │   17     │   │  Celery  │
                         └──────────┘   └──────────┘
```

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) for the full
system overview and [docs/architecture/COMPONENTS.md](docs/architecture/COMPONENTS.md)
for component responsibilities.

## Documentation

| Topic | Location |
| --- | --- |
| System overview and request flows | [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) |
| Component responsibilities | [docs/architecture/COMPONENTS.md](docs/architecture/COMPONENTS.md) |
| Authentication and authorization | [docs/architecture/AUTH.md](docs/architecture/AUTH.md) |
| Server spawn/start/stop/delete lifecycle | [docs/architecture/SERVER-LIFECYCLE.md](docs/architecture/SERVER-LIFECYCLE.md) |
| Core data model | [docs/architecture/DATA-MODEL.md](docs/architecture/DATA-MODEL.md) |
| Local development | [docs/development/LOCAL-DEV.md](docs/development/LOCAL-DEV.md) |
| Contributing guidelines | [docs/development/CONTRIBUTING.md](docs/development/CONTRIBUTING.md) |
| Operations (DB, backups, scaling) | [docs/operations/OPERATIONS.md](docs/operations/OPERATIONS.md) |
| Production deployment | [docs/operations/PRODUCTION-DEPLOYMENT.md](docs/operations/PRODUCTION-DEPLOYMENT.md) |
| Backup and restore | [docs/operations/BACKUP-RESTORE.md](docs/operations/BACKUP-RESTORE.md) |
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
