# NukeLab Architecture Overview

NukeLab is a multi-user scientific computing platform. It exposes a web management interface, a REST API, and per-user interactive development environments (NukeIDE containers) running as isolated Docker/Podman containers.

## High-level request flow

```
                         +--------------------------------+
                         |          Traefik v3            |
                         |  Reverse proxy + TLS + routing |
                         |                                |
                         |   /*      /api/*    /user/{u}/*|
                         +------+--------+-------------+--+
                                |        |             |
                                v        v             v
                         +----------+  +----------+  +--------------+
                         |  Vite    |  | FastAPI  |  |   NukeIDE    |
                         |  React   |  | Backend  |  |  Container   |
                         |   SPA    |  |          |  | (nginx +     |
                         |          |  |          |  |  Theia IDE)  |
                         +-----+----+  +-----+----+  +------+-------+
                               |             |              |
                               |             |              |
                               +-------------+--------------+
                                             |
                          +------------------+------------------+
                          v                  v                  v
                    +----------+      +----------+      +----------+
                    |PostgreSQL|      |  Redis   |      |  Celery  |
                    |    17    |      |          |      | Workers  |
                    +----------+      +----------+      +----------+
```

## What each path is for

| Route prefix | Destination | Purpose |
|---|---|---|
| `/*` | Vite React SPA | Management dashboard and user portal |
| `/api/*` | FastAPI backend | REST API, WebSocket upgrades, health checks |
| `/user/{username}/*` | User container | NukeIDE interactive environment |

## Runtime boundaries

### User-facing layer

- **Traefik** handles TLS termination, routing, rate limiting, and WebSocket upgrades.
- **Frontend** is a static Vite + React 19 SPA. It calls `/api/*` and subscribes to `/ws` for real-time events.
- **NukeIDE containers** are spawned on demand. Each container's nginx proxy delegates token validation to a local Go auth sidecar before forwarding to the Theia IDE backend.

### API and orchestration layer

- **FastAPI backend** (`backend/app/main.py`) owns auth, user/server/environment/plan management, audit logging, metrics, Docker orchestration, and owner/admin batch-job surfaces.
- **ContainerDriver** (`backend/app/container/driver.py`) and `DockerDriver` (`aiodocker`) provide the low-level runtime abstraction selected by `CONTAINER_RUNTIME`; `ContainerClient` is a compatibility shim.
- **ServerSpawner** (`backend/app/container/spawner.py`) coordinates higher-level server lifecycle actions (volume creation, image pulling, Traefik labels, readiness checks).
- **Queue, launch, lifecycle, provenance, batch-job and recovery services** persist owner intent before runtime I/O, enforce admission and authorization, and reconcile uncertain outcomes.
- **Celery workers** run background tasks: NUKE billing, server cleanup, queue dispatch, batch-job dispatch/monitoring/recovery, scheduled start/stop, notifications, maintenance windows, recovery scans, and recovery retention.

### Data and state layer

- **PostgreSQL 17** stores users, roles, permissions, servers, environments, plans, credit transactions, audit logs, launch provenance, batch-job journals and bounded logs, recovery records and metrics history. Time-series tables are partitioned by month.
- **Redis** handles token denylist/revocation state, pub/sub, Celery broker duties, response caching, rate limits, and real-time message distribution.
- **Private volume backups** live under an operator-configured host path that the API/workers and the trusted recovery helper reach through the same bind mount.

## Key design decisions

- **Vite SPA instead of Next.js.** The dashboard is authenticated, real-time, and dynamic. Eliminating a Node.js server runtime frees memory for user containers.
- **FastAPI instead of Django.** Native async/await, WebSocket support, and Pydantic validation fit an I/O-bound platform that calls the Docker API frequently.
- **Traefik instead of Nginx.** Native Docker auto-discovery is required for dynamic user container routing.
- **PostgreSQL instead of a separate time-series database.** The workload fits relational queries with monthly partitioning for audit and metrics tables.
- **Durable intent instead of best-effort provisioning.** Queue requests, lifecycle reservations, batch-job reservations and launch provenance are persisted before runtime I/O so uncertain outcomes can be fenced and reconciled instead of silently duplicated.

## Scaling notes

Current hardware constraints drove several design choices:

- A **NUKE credit system** prevents resource monopolization.
- **Queue-based scheduling** starts servers when resources become available.
- **Idle auto-stop** and **max runtime** reclaim resources automatically.
- Horizontal scaling is a future phase; the data model and routing are designed to accommodate multiple worker hosts.

See [COMPONENTS.md](COMPONENTS.md) for detailed component responsibilities, [BATCH-JOBS.md](BATCH-JOBS.md) for single-run execution, [AUTH.md](AUTH.md) for auth flows, [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for container lifecycle, and [DATA-MODEL.md](DATA-MODEL.md) for core entities.
