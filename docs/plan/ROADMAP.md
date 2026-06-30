# NukeLab Roadmap

**Status**: Phases 1–5, 7, and 8 complete. Platform is production-hardened on Docker/Podman.  
**Last Updated**: June 30, 2026  
**Tech Stack**: Vite + React 19 SPA, FastAPI (Python 3.13), PostgreSQL 17, Redis, Traefik v3, Docker/Podman

## Recent milestones

- **System Config API** (`/api/system/config`, `/api/system/stats`)
- **Maintenance Mode** — Toggle platform on/off with 503 response
- **Audit Log Export** — CSV/JSON export (`/api/admin/activity/export`)
- **Rate Limiting** — slowapi integration and Traefik DDoS protection
- **Server Scheduling** — Cron-based schedules with visual builder UI
- **Shared Workspaces** — Volume sharing with member/invitation management
- **Notification Center** — In-app + email notifications with WebSocket delivery
- **Usage Trends** — Per-user and platform-wide historical charts (7d/30d/90d)
- **Permission Matrix Editor** — Full RBAC matrix UI
- **Bulk Operations** — Server start/stop/restart/delete; workspace activate/deactivate/delete; volume activate/archive/delete
- **Quick Spawn** — `Alt+N` opens deploy dialog pre-filled with saved user preferences
- **Default Spawn Preferences** — Settings UI for default plan + environment
- **Health Check Auto-Restart** — Rate-limited auto-restart for unhealthy containers
- **IP Allowlist/Blocklist** — Middleware + admin CRUD API + UI; CIDR support; self-block prevention
- **CSRF Double-Submit Protection** — Cookie/header pattern with smart exemptions
- **Security Headers (Exception-Safe ASGI)** — Injected even on 500 errors
- **Path Traversal Fix** — Centralized `secure_path()` utility
- **Production Secret Validation** — App refuses to start with default secrets
- **Structured Logging** — JSON/text formatters, correlation IDs, Celery propagation
- **HTTP Request Metrics** — `RequestMetric` model, route-aware normalization, batched writes, admin analytics
- **Graceful Shutdown** — `ShutdownCoordinator` with bounded timeouts
- **Request Size Limits** — 10 MB default with chunked-transfer abort
- **Strict CORS** — Explicit origin whitelist, preflight caching, rejects `*` with credentials
- **Redis Response Caching** — msgpack serialization, circuit breaker, stampede protection, SET invalidation
- **OpenTelemetry Distributed Tracing** — End-to-end across FastAPI, Celery, SQLAlchemy, Redis
- **CI/CD Pipeline** — GitHub Actions lint/test/build/push, path-filtered
- **Load Testing** — Locust/k6 hybrid, five profiles, PgBouncer connection flood

See [IMPLEMENTATION-PHASES.md](IMPLEMENTATION-PHASES.md) for the full phase-by-phase record.

## Model highlights

- **ServerPlan** — `max_runtime`, `idle_timeout`, `allow_scheduling`, `allow_snapshots`
- **Server** — `health_status`, `health_check_config`, `last_health_check`, `status_reason`, `stopped_by`, `stop_reason`
- **ServerQueue** — `requested_cpu`, `requested_memory`, `requested_disk`

## Test coverage

- 2,600+ backend tests passing
- Coverage spans auth, RBAC, servers, volumes, workspaces, credits, plans, environments, admin, bulk ops, security middleware, caching, logging, graceful shutdown, and rate limiting.

## Active priorities

1. **Environment image build pipeline** — automated builds, registry integration, image versioning, base-image updates
2. **Blue-green deployment** — zero-downtime deploy strategy
3. **Secret management** — HashiCorp Vault or sealed secrets integration
4. **Penetration testing** — third-party assessment before public production launch

## Deferred goals

- Kubernetes migration (Helm, HPA, PVCs, Network Policies, Pod Security Standards)
- GPU allocation and metrics
- Blue-green/rollback deployment automation
- Marketplace / plugin system

Pursue Kubernetes only after saturating a single large server (32+ cores, 128GB+ RAM) and proving distribution is required.

## Decision log

See [DECISION-LOG.md](DECISION-LOG.md).
