# NukeLab Server Lifecycle

This document describes the lifecycle of a NukeLab server, from initial spawn request through deletion.

## Lifecycle states

A server can be in one of these states:

| State | Meaning |
|---|---|
| `pending` | Spawn request accepted, resources being allocated |
| `starting` | Container is being created and started |
| `running` | Container is active and accessible |
| `stopping` | Stop request received, container is shutting down |
| `stopped` | Container is stopped but the server record remains |
| `error` | An error occurred during spawn or operation |

## Spawn flow

```
User clicks "Spawn"
        |
        v
POST /api/servers
        |
        v
FastAPI validates auth, permissions, quota, credits
        |
        v
ResourcePoolService checks available CPU, memory, disk
        |
        +---> Insufficient resources ---> Queue server request
        |
        +---> Resources available
                |
                v
        ServerSpawner.spawn()
                |
                +---> Ensure persistent volume exists
                |
                +---> Pull environment image if missing
                |
                +---> Create container with plan limits
                |     (NanoCpus, Memory, Cpuset, StorageOpt)
                |
                +---> Attach Traefik routing labels
                |     traefik.http.routers.{name}.rule=Host(...) && PathPrefix(/user/{username}/{server_id})
                |
                +---> Start container
                |
                +---> Wait for readiness via HTTP health check
                |
                v
        Update server status to running
                |
                v
        Publish WebSocket event server.status_changed
```

## Start flow

Starting a stopped server reuses the existing container if possible. If the container is missing (for example, after a host restart), the spawner recreates it from the server record.

```
POST /api/servers/{id}/start
        |
        v
Validate credits and quota
        |
        v
Check existing container
        |
        +---> Container exists ---> Start it
        |
        +---> Container missing ---> Recreate from server record
                |
                v
        Wait for readiness
                |
                v
        Update status and emit event
```

## Stop flow

```
POST /api/servers/{id}/stop
        |
        v
FastAPI records actor and reason
        |
        v
ContainerClient.stop_container()
        |
        +---> Send SIGTERM with configurable timeout
        |
        +---> Force kill if timeout exceeded
        |
        v
Update server status to stopped
        |
        v
Emit server.status_changed event
```

## Restart flow

Restart is implemented as a stop followed by a start, preserving the same server record and volumes.

## Delete flow

```
DELETE /api/servers/{id}
        |
        v
Validate delete permission
        |
        v
Stop container if running
        |
        v
Delete container
        |
        v
Optionally delete associated volumes (admin-only bulk action)
        |
        v
Mark server as deleted or remove record
        |
        v
Emit server.status_changed event
```

## Scheduling

Celery Beat runs cron-based schedules defined in `ServerSchedule`. When a schedule fires, Celery calls the same start/stop service methods used by the API, ensuring consistent validation and audit logging.

## Health checks

`HealthCheckService` periodically probes running containers. If a container is unhealthy, the backend can auto-restart it subject to rate limits. Health status is stored on the `Server` model and surfaced in the dashboard.

## Resource cleanup

Background tasks handle cleanup:

- NUKE billing debits credits for running servers.
- Idle servers are stopped after the configured `idle_timeout`.
- Servers exceeding `max_runtime` are stopped automatically.
- Expired guest accounts and stale notification records are pruned.

## Code locations

| Responsibility | File |
|---|---|
| API routes | `backend/app/api/servers.py` |
| Spawn orchestration | `backend/app/container/spawner.py` |
| Low-level container ops | `backend/app/container/client.py` |
| Resource availability | `backend/app/services/resource_pool_service.py` |
| Health checks | `backend/app/services/health_check_service.py` |
| Scheduling | `backend/app/services/schedule_service.py` |
| Background billing/cleanup | `backend/app/tasks.py` |

## Related documents

- [COMPONENTS.md](COMPONENTS.md) for how ContainerClient and ServerSpawner fit into the system
- [AUTH.md](AUTH.md) for container access authentication
- [DATA-MODEL.md](DATA-MODEL.md) for the Server entity and state fields
- [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for cgroup and resource isolation details
