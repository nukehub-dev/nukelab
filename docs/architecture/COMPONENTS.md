# NukeLab Component Responsibilities

This document describes the major runtime components, their responsibilities, and how they interact.

## Component inventory

| Component | Technology | Primary responsibility |
|---|---|---|
| Reverse proxy | Traefik v3 | Dynamic routing, TLS termination, WebSocket proxying, rate limiting |
| Frontend | Vite + React 19 SPA | Dashboard, user portal, real-time monitoring UI |
| Backend API | FastAPI (Python 3.13) | Auth, user/server/environment/plan management, Docker orchestration, metrics |
| Container client | Docker SDK via `ContainerClient` | Low-level container operations: create, start, stop, delete, logs, stats |
| Server spawner | `ServerSpawner` | High-level server lifecycle coordination: volumes, images, labels, readiness |
| Database | PostgreSQL 17 | Relational data, audit logs, metrics history with partitioning |
| Cache / queue | Redis | Sessions, pub/sub, Celery broker, response cache, real-time message bus |
| Background workers | Celery + Celery Beat | Billing, cleanup, scheduled tasks, notifications, maintenance windows |
| User environments | NukeIDE (nginx + Theia) | Per-user interactive development environment with JWT proxy |
| Observability | Prometheus, Grafana, Alertmanager, Jaeger, OTel | Metrics, dashboards, alerts, distributed traces |

## Interaction matrix

```
Browser
  |
  +---> Traefik ---> Frontend SPA (static files)
  |
  +---> Traefik ---> FastAPI ---> PostgreSQL
  |                   |    |
  |                   |    +---> Redis
  |                   |    |
  |                   |    +---> Celery workers
  |                   |
  |                   +---> Docker/Podman daemon
  |                          |
  |                          +---> ContainerClient / ServerSpawner
  |
  +---> Traefik ---> NukeIDE container ---> nginx auth proxy ---> Theia
```

## Per-component responsibilities

### Traefik

- Routes `/*` to the frontend container
- Routes `/api/*` and `/ws` to the FastAPI backend
- Discovers and routes `/user/{username}/{server_id}` to spawned user containers via Docker labels
- Terminates TLS (when configured)
- Applies rate limits and security headers

### Frontend (Vite + React 19 SPA)

- Provides the admin dashboard and user portal
- Uses TanStack Router for type-safe routing
- Uses TanStack Query for server state, polling, and caching
- Subscribes to `/ws` for real-time server status and metrics events
- Built as static files; requires no Node.js runtime in production

### FastAPI backend

- Exposes REST endpoints under `/api/*`
- Validates JWT access tokens signed with EdDSA (Ed25519)
- Enforces RBAC through role and permission checks
- Handles server spawn/start/stop/restart/delete requests
- Manages users, environments, plans, credits, quotas, workspaces, volumes, and notifications
- Writes audit logs and request metrics
- Exposes Prometheus metrics at `/api/metrics` when enabled
- Implements graceful shutdown via `ShutdownCoordinator`

### ContainerClient

Location: `backend/app/container/client.py`

Responsibilities:

- Connect to the Docker/Podman socket
- Pull images
- Create containers with cgroup limits, volume mounts, security options, and Traefik labels
- Start, stop, and delete containers
- Wait for container readiness via HTTP health checks
- Stream and fetch container logs
- Collect container stats for metrics
- Manage lxcfs mounts and CPU visibility helpers

### ServerSpawner

Location: `backend/app/container/spawner.py`

Responsibilities:

- Coordinate server creation from environment templates and resource plans
- Ensure persistent volumes exist before spawning
- Translate plans into Docker resource limits
- Generate container names and external URLs
- Attach Traefik routing labels
- Handle start/stop/delete lifecycle transitions and cleanup

### PostgreSQL

Responsibilities:

- Store relational application data
- Store immutable audit logs
- Store time-series metrics history in partitioned tables (`activity_logs`, `server_metrics`, `request_metrics`)
- Support asyncpg/SQLAlchemy 2 queries from the backend

### Redis

Responsibilities:

- Session and token denylist storage
- Celery broker and result backend
- Pub/sub for real-time WebSocket message distribution
- Response caching for frequently read endpoints
- Rate limit counters (optional)

### Celery

Responsibilities:

- Debit NUKE credits for running servers
- Process scheduled server start/stop actions
- Send notifications (in-app, email, WebSocket)
- Execute maintenance window enable/disable
- Run periodic cleanup and health tasks

### NukeIDE container

Responsibilities:

- Provide an interactive IDE (Theia) per user server
- Validate server-scoped tokens in an nginx auth proxy
- Enforce that only the owning user (or authorized support/admin) can access the IDE
- Report container health to the backend

## Deployment overlays

Optional compose overlays extend the core stack:

| Overlay file | Adds |
|---|---|
| `compose.monitoring.yml` | Prometheus, Grafana, Alertmanager, exporters |
| `compose.pgbouncer.yml` | PgBouncer connection pooler |
| `compose.monitoring-pgbouncer.yml` | PgBouncer metrics exporter |
| `compose.tracing.yml` | OpenTelemetry collector and Jaeger |
| `compose.loadtest.yml` | Load testing tooling |

See [MONITORING.md](MONITORING.md) for observability details and [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for deployment guidance.
