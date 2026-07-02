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
                    |    18    |      |          |      | Workers  |
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
- **NukeIDE containers** are spawned on demand. Each container runs an nginx proxy that validates short-lived server tokens before forwarding to the Theia IDE backend.

### API and orchestration layer

- **FastAPI backend** (`backend/app/main.py`) owns auth, user/server/environment/plan management, audit logging, metrics, and Docker orchestration.
- **ContainerClient** (`backend/app/container/client.py`) wraps the Docker SDK for low-level container operations.
- **ServerSpawner** (`backend/app/container/spawner.py`) coordinates higher-level server lifecycle actions (volume creation, image pulling, Traefik labels, readiness checks).
- **Celery workers** run background tasks: NUKE billing, server cleanup, scheduled start/stop, notifications, and maintenance windows.

### Data and state layer

- **PostgreSQL 17** stores users, roles, permissions, servers, environments, plans, credit transactions, audit logs, and metrics history. Time-series tables are partitioned by month.
- **Redis** handles sessions, pub/sub, Celery broker duties, response caching, and real-time message distribution.

## Key design decisions

- **Vite SPA instead of Next.js.** The dashboard is authenticated, real-time, and dynamic. Eliminating a Node.js server runtime frees memory for user containers.
- **FastAPI instead of Django.** Native async/await, WebSocket support, and Pydantic validation fit an I/O-bound platform that calls the Docker API frequently.
- **Traefik instead of Nginx.** Native Docker auto-discovery is required for dynamic user container routing.
- **PostgreSQL instead of a separate time-series database.** The workload fits relational queries with monthly partitioning for audit and metrics tables.

## Scaling notes

Current hardware constraints drove several design choices:

- A **NUKE credit system** prevents resource monopolization.
- **Queue-based scheduling** starts servers when resources become available.
- **Idle auto-stop** and **max runtime** reclaim resources automatically.
- Horizontal scaling is a future phase; the data model and routing are designed to accommodate multiple worker hosts.

See [COMPONENTS.md](COMPONENTS.md) for detailed component responsibilities, [AUTH.md](AUTH.md) for auth flows, [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for container lifecycle, and [DATA-MODEL.md](DATA-MODEL.md) for core entities.
