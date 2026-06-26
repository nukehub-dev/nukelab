# NukeLab Platform v2.0 — Architecture & Implementation Plan

**Status**: Phase 5 & Phase 7 100% Complete · Phase 8 Load Testing Delivered · CI/CD Pipeline Implemented · Redis Alert Hardened
**Last Updated**: June 26, 2026  
**Target Timeline**: 6+ months  
**Tech Stack**: Vite + React 19 SPA, FastAPI, PostgreSQL 18, Redis, Traefik v3, Docker/Podman

---

## Recent Updates (May 2026)

### New Features Implemented
- **System Config API** (`/api/system/config`, `/api/system/stats`)
- **Maintenance Mode** — Toggle platform on/off with 503 response
- **Audit Log Export** — CSV/JSON export (`/api/admin/activity/export`)
- **Rate Limiting** — slowapi integration (10/minute on login)
- **Server Scheduling** — Cron-based schedules with visual builder UI
- **Shared Workspaces** — Volume sharing with member/invitation management
- **Notification Center** — In-app + email notifications with WebSocket delivery
- **Usage Trends** — Per-user and platform-wide historical charts (7d/30d/90d)
- **Permission Matrix Editor** — Full RBAC matrix UI
- **Bulk Operations** — Server start/stop/restart/delete, workspace activate/deactivate/delete, volume activate/archive/delete
- **Quick Spawn** — `Alt+N` opens deploy dialog pre-filled with saved user preferences
- **Default Spawn Preferences** — Settings UI for default plan + environment
- **Health Check Auto-Restart** — Rate-limited auto-restart for unhealthy containers
- **Real Health Endpoint Values** — Dashboard system health aggregates actual Postgres/Redis/Docker checks
- **IP Allowlist/Blocklist** — Full middleware + admin CRUD API + UI; CIDR support; self-block prevention; exempt paths (auth, health, docs)
- **Quota Service Disk Bug Fix** — Removed double-counting of server `allocated_disk` + volume `max_size_bytes`; volume creation quota now counts volumes separately
- **Admin Volume Edit UX** — Replaced raw bytes input with GB slider (1–500 GB); synced with user volume create dialog pattern
- **Volume Max Size Validation** — Shared `VolumeService.validate_max_size()` prevents shrinking below actual used bytes on both user and admin endpoints
- **Security Headers (Exception-Safe ASGI)** — `SecurityHeadersMiddleware` intercepts `http.response.start` to inject headers even on 500 errors; adds `Cross-Origin-Resource-Policy`, `Cache-Control: no-store` on auth/admin, `Clear-Site-Data` on logout
- **Path Traversal Fix** — Centralized `secure_path()` utility with `pathlib.Path.resolve()` + `relative_to()` validation; avatar endpoint has filename whitelist + path resolution defense-in-depth
- **Production Secret Validation** — App refuses to start in production with default `JWT_SECRET` or `SESSION_SECRET`
- **CSRF Double-Submit Protection** — `CSRFProtectMiddleware` enforces `X-CSRF-Token` header matching `csrf_token` cookie for cookie-authenticated state-changing requests; smart exemptions for Bearer auth, safe methods, and auth flow endpoints
- **Removed Harmful `browserXssFilter`** — Deleted from Traefik config (XSS Auditor creates XS-Leak side channels)
- **Disabled Traefik Dashboard** — Removed `api.insecure` and dashboard router labels from default config
- **Scheduled Maintenance Windows** — Pre-planned maintenance with auto-enable/disable via Celery; 15-minute advance notifications to all active users (in-app + email + WebSocket)
- **Structured Logging** — JSON/text formatters, correlation IDs via `contextvars`, Celery cross-thread propagation; ~46 `print()` replacements
- **HTTP Request Metrics** — `RequestMetric` model, route-aware normalization, batched DB writes (100/5s), admin dashboard at `/admin/analytics`, 30-day retention
- **Graceful Shutdown** — `ShutdownCoordinator` with bounded timeouts: background task cancellation (3s), WebSocket drain (3s), metrics flush (5s), Redis stop (3s), DB engine dispose (3s); `/health` returns 503 during shutdown
- **Request Size Limits** — `RequestSizeLimitMiddleware` with O(1) Content-Length fast path and chunked-transfer abort; 10 MB default
- **Strict CORS** — Explicit origin whitelist, restricted methods/headers in production, preflight caching; rejects `*` with credentials
- **Redis Response Caching** — `app.core.cache` with msgpack serialization, circuit breaker, stampede protection, and SET-based invalidation; caches `GET /servers/` and `GET /admin/servers` with 30s TTL; complete invalidation on all mutations
- **OpenTelemetry Distributed Tracing** — end-to-end tracing across FastAPI, Celery, SQLAlchemy, Redis; OTLP exporter to collector; Jaeger UI at `/jaeger`; Grafana Jaeger datasource; preserves existing correlation ID logging
- **CI/CD Pipeline** — GitHub Actions workflow (`.github/workflows/ci.yml`) lints backend/frontend, runs backend tests, and builds/pushes `backend`, `frontend`, and `auth-sidecar` images to GitHub Container Registry with path-filtered jobs and branch/tag-based image tags
- **Dev/Prod Isolation in nukelabctl** — `dev` meta-command with separate state files; mutual exclusion so `start` and `dev start` cannot overlap; `loadtest` always targets production
- **Redis maxmemory & Alert Hardening** — Redis defaults to `256mb` with `allkeys-lru`; Prometheus alert guards against division-by-zero when `maxmemory` is unset and warns when it is not configured

### Model Updates
- **ServerPlan** — Added `max_runtime`, `idle_timeout`, `allow_scheduling`, `allow_snapshots`
- **Server** — Added `health_status`, `health_check_config`, `last_health_check`, `status_reason`, `stopped_by`, `stop_reason`
- **ServerQueue** — Added `requested_cpu`, `requested_memory`, `requested_disk`

### Tests
- 500+ tests passing
- Test files: `test_system.py`, `test_plans.py`, `test_credits.py`, `test_environments.py`, `test_auth.py`, `test_bulk.py`, `test_admin_workspaces.py`, `test_admin_volumes.py`, `test_ip_restrictions.py`, `test_volumes.py`, `test_security_headers.py`, `test_filesystem.py`, `test_config.py`, `test_csrf.py`, `test_maintenance_windows.py`, `test_shutdown.py`, `test_logging.py`, `test_request_size_limit.py`, `test_websocket_shutdown.py`, `test_cache.py`, `test_redis_client.py`, `test_roles_cache.py`

---

## 1. Executive Summary

NukeLab v2.0 is a ground-up rebuild of the multi-user scientific computing platform, replacing JupyterHub with a custom industrial-grade orchestration layer. The platform provides granular RBAC, real-time resource monitoring, multi-environment support, and a modern Vite + React 19 SPA management interface.

**Key Improvements over v1.0:**
- Granular role-based access control (6+ roles, 20+ permissions)
- Real-time per-container resource monitoring (CPU, memory, disk)
- Admin-configurable environment templates with Docker images, packages, env vars
- Modern Vite + React 19 admin dashboard with live metrics
- Audit logging for compliance
- Server scheduling (cron-based start/stop)
- Shared workspaces with permission management
- Notification center (in-app + email)
- WebSocket-native architecture
- Kubernetes migration path (future)

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Traefik v3 (Reverse Proxy)                   │
│                                                                  │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐   │
│  │ /*         │  │ /api/*     │  │ /user/{username}/*       │   │
│  │ → Vite SPA │  │ → FastAPI  │  │ → NukeIDE Container      │   │
│  │   Frontend │  │   Backend  │  │   (Nginx + Theia)        │   │
│  └────────────┘  └────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Vite + React  │    │  FastAPI Backend │    │  PostgreSQL  │
│  19 SPA      │◄──►│  + WebSocket     │    │  18 + Redis  │
│  Tailwind    │    │  + Docker SDK    │    │              │
└──────────────┘    └──────────────────┘    └──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Celery Workers  │
                    │  (Background     │
                    │   tasks)         │
                    └──────────────────┘
```

### 2.1 Component Responsibilities

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Reverse Proxy** | Traefik v3 | Dynamic routing, TLS termination, WebSocket proxying, rate limiting |
| **Frontend** | Vite + React 19 SPA | Admin dashboard, user portal, real-time monitoring UI |
| **Backend API** | FastAPI | Auth, user/server management, Docker orchestration, metrics collection |
| **Database** | PostgreSQL 18 | Users, roles, permissions, environments, servers, audit logs, metrics history |
| **Cache/Queue** | Redis | Sessions, pub/sub, Celery broker, real-time message bus |
| **Background Workers** | Celery | Server cleanup, notifications, report generation, scheduled tasks |
| **User Environments** | NukeIDE + Nginx | Theia IDE with built-in JWT validation proxy |

### 2.2 Hardware Constraints

Current infrastructure is limited and requires careful resource management:

| Server | CPU | Memory | Disk | Role |
|--------|-----|--------|------|------|
| **Main Server** | 32 cores | 64GB RAM | 1TB HDD | Primary compute + system services |
| **Contabo VPS** | 6 cores | 12GB RAM | 200GB SSD | Secondary compute / backup |
| **Total Available** | ~34 cores | ~68GB RAM | ~1.1TB | After system reservation |

**Implications:**
- Credit system required to prevent resource monopolization
- Queue-based scheduling when resources unavailable
- Auto-culling of idle servers essential
- Plans must respect total available resources
- Horizontal scaling needed for growth (Phase 6)

---

## 3. Technology Stack Decisions

### 3.1 Why FastAPI over Django?

| Factor | FastAPI | Django |
|--------|---------|--------|
| **Concurrency** | Native async/await (high I/O throughput) | Sync by default (ASGI available but less mature) |
| **WebSocket** | Native support, clean API | Channels required, more complex |
| **Docker SDK** | Async docker SDK integrates seamlessly | Same SDK but sync blocks |
| **API Docs** | Auto-generated OpenAPI/Swagger | DRF required |
| **Performance** | ~10x more concurrent connections | Simpler for CRUD, slower for I/O-bound |
| **Type Safety** | Native Pydantic validation | DRF serializers |

**Decision**: FastAPI is optimal for an I/O-bound platform making frequent Docker API calls and maintaining many concurrent WebSocket connections.

### 3.2 Why Vite + React 19 SPA + TanStack Router + TanStack Query?

| Factor | Next.js 16 App Router | Vite + React 19 SPA |
|--------|----------------------|---------------------|
| **SSR/SSG** | Built-in Server Components | Client-side only |
| **Runtime** | Requires Node.js server | Static files only |
| **Real-time** | Server-Sent Events + WebSocket | Native WebSocket |
| **Build Speed** | Turbopack stable | Vite HMR, near-instant |
| **Caching** | Aggressive server caching | No server cache fights |
| **State Management** | React Server Components complexity | TanStack Query handles async |
| **SEO** | Excellent | Poor (irrelevant for dashboard) |
| **Resource Usage** | Higher RAM/CPU for SSR | Minimal runtime footprint |

**Decision**: Vite + React 19 SPA + TanStack Router + TanStack Query

**Why**: The platform is an authenticated, real-time dashboard heavily reliant on WebSockets and live Docker state. Server-Side Rendering (SSR) provides zero SEO benefit here and consumes valuable hardware resources. A Vite SPA compiles to static files, requiring no Node.js runtime, freeing up maximum RAM for the user simulation containers.

**Key Benefits**:
- **Zero Server Runtime**: Compiled static assets served by Nginx or Traefik directly — no Node.js process consuming RAM
- **TanStack Query**: Robust polling, caching, and WebSocket state management without fighting Next.js's aggressive server caching
- **TanStack Router**: Type-safe routing with first-class search params, layout routes, and data loading
- **React 19**: Native View Transitions, Activity API, improved concurrent features, automatic memoization
- **Vite Ecosystem**: Instant HMR, optimized builds, mature plugin ecosystem
- **Hardware Efficiency**: On our 64GB RAM constraint, every megabyte counts — eliminating the Node.js frontend runtime saves resources for user containers

**Trade-off Accepted**: No SSR/SSG. For an authenticated admin dashboard, SEO is irrelevant. All data is dynamic and user-specific anyway.

### 3.3 Why Traefik v3 over Nginx?

| Factor | Traefik v3 | Nginx |
|--------|-----------|-------|
| **Dynamic Routing** | Auto-discovers Docker containers | Requires config reloads |
| **WebSocket** | Native, zero config | Requires manual upgrade headers |
| **Kubernetes** | Native CRD support | Separate Ingress Controller |
| **Performance** | Very good (Go-based) | Best raw throughput |
| **Config Complexity** | Labels on containers | Config files + reloads |

**Decision**: Traefik v3's native Docker auto-discovery is critical for dynamic user container routing. Performance difference is negligible for this use case.

### 3.4 Why PostgreSQL 18?

- Latest stable release with improved JSONB performance
- Better partitioning for large audit log tables
- Native support for advanced indexing (BRIN for time-series metrics)
- Strong ACID compliance for user data and permissions

---

## 4. Core Features Design

### 4.1 Granular RBAC System

#### Roles

| Role | Description |
|------|-------------|
| `super_admin` | Full system access, platform configuration, can modify roles |
| `admin` | Full user/server management, can access any user server (audit trail required) |
| `moderator` | Can CRUD users, view all servers/resources, **cannot** access user servers |
| `support` | Can view users and servers, can access user servers for debugging (audit trail) |
| `user` | Can manage own servers, view own resources, limited by quotas |
| `guest` | Temporary access, severely limited resources, auto-expires after configured time |

#### Permission Matrix

```
users:read            - View user list and profiles
users:create          - Create new users
users:update          - Modify user properties
users:delete          - Permanently delete users
users:disable         - Disable/enable user accounts
users:impersonate     - Login as another user

servers:read_own      - View own servers
servers:read_all      - View all users' servers
servers:start         - Start a server
servers:stop          - Stop a server
servers:restart       - Restart a server
servers:delete        - Delete a server
servers:access_own    - Access own NukeIDE session
servers:access_all    - Access any user's NukeIDE session

resources:read_own    - View own resource usage
resources:read_all    - View all users' resource usage
resources:monitor     - Access real-time monitoring dashboard

environments:read     - View environment templates
environments:create   - Create new environment templates
environments:update   - Modify environment templates
environments:delete   - Delete environment templates

audit:read            - View audit logs
audit:export          - Export audit logs

system:config         - Modify platform configuration
system:maintenance    - Enable/disable maintenance mode
```

#### Permission Assignment

- Roles are predefined with default permissions
- Super admin can customize permissions per role
- Individual user permission overrides supported
- Groups/organizations can have role templates

### 4.2 Environment Templates

Environment templates are **admin-created** Docker images that define what tools and libraries are available in a server container. Unlike predefined hardcoded environments, admins can create, update, clone, and delete environments through the admin panel.

#### Environment Properties

```yaml
name: "Scientific Computing"
slug: "sci-compute"
description: "Python + Jupyter + common scientific libraries"
image: "nukelab/scientific:latest"
dockerfile: "# Optional: custom Dockerfile"
packages: ["jupyter", "numpy", "pandas", "matplotlib", "scipy"]
environment_variables:
  JUPYTER_ENABLE_LAB: "yes"
volumes: ["/data:/data:ro"]
ports: [3000, 8888]
icon: "🧪"
color: "#3B82F6"
category: "scientific"
is_public: true
created_by: "admin-id"
```

#### Admin CRUD Operations

- **Create**: Admins create environments with name, slug, Docker image, packages, env vars, ports
- **Clone**: Duplicate existing environment as template for new variations
- **Update**: Modify packages, env vars, ports, metadata
- **Deactivate/Activate**: Soft-disable without deleting (prevents new servers from using it)
- **Delete**: Permanent removal (only if no active servers use it)

### 4.3 Server Plans (Resource Tiers)

Server Plans define resource allocations independent of environment templates. Users select both an **environment** (what tools are installed) and a **plan** (how much resources they get).

#### Predefined Plans

| Plan | CPU | Memory | Disk | GPU | Max/User | Description |
|------|-----|--------|------|-----|----------|-------------|
| `small` | 2 | 4GB | 20GB | 0 | 4 | Development, Jupyter notebooks, light analysis |
| `medium` | 4 | 8GB | 50GB | 0 | 3 | Standard simulations, data processing |
| `large` | 8 | 16GB | 100GB | 0 | 2 | Heavy simulations, parallel CPU workloads |
| `xlarge` | 16 | 32GB | 200GB | 0 | 1 | Maximum resources — admin approval required |

#### Plan Properties

```yaml
name: "medium"
description: "Standard simulation tier"
resources:
  cpu: 4
  memory: "8Gi"
  disk: "100Gi"
  gpu: 0
features:
  max_runtime: "24h"           # Auto-stop after 24 hours
  idle_timeout: "1h"           # Stop after 1 hour idle
  allow_scheduling: true       # Can schedule start/stop
  allow_snapshots: true        # Can create snapshots
  priority: "normal"           # Scheduling priority
restrictions:
  min_role: "user"            # Minimum role required
  max_per_user: 3             # Max servers with this plan
  requires_approval: false    # Admin approval needed
pricing:
  nukes_per_hour: 1          # Cost in NUKE currency
```

#### Plan Selection Flow

```
User spawns server:
  1. Select Environment (from admin-created templates)
  2. Select Plan (small, medium, large, xlarge)
  3. Optional: Customize resources within plan limits
  4. Optional: Select duration / schedule
  5. Confirm and spawn
```

#### Custom Plans per User

Admins can assign custom resource limits to specific users:

```yaml
user: "john.doe"
custom_plan:
  cpu: 32
  memory: "64Gi"
  disk: "1Ti"
  gpu: 2
  max_runtime: "72h"
  reason: "PhD research - parallel simulations"
approved_by: "admin"
approved_at: "2026-04-27T10:00:00Z"
expires_at: "2026-12-31T23:59:59Z"
```

#### Plan Inheritance

```
Default Plan (system default)
  └── Role Default Plan (override per role)
       └── Group Plan (override per group)
            └── User Custom Plan (override per user)
                 └── Server Override (one-time override)
```

### 4.4 NUKE Currency System

With limited hardware resources (38 CPU total, 76GB RAM), a NUKE-based currency system ensures fair usage and prevents resource monopolization.

#### NUKE Model

```
NUKE = Resource × Time × Plan Multiplier

Example:
  small plan (2 CPU, 4GB) running for 1 hour:
    Base cost: 1 NUKE/hour
    
  medium plan (4 CPU, 8GB) running for 1 hour:
    Base cost: 2 NUKE/hour
    
  large plan (8 CPU, 16GB) running for 1 hour:
    Base cost: 4 NUKE/hour

  xlarge plan (16 CPU, 32GB) running for 1 hour:
    Base cost: 8 NUKE/hour
```

#### NUKE Sources

| Source | Amount | Frequency | Description |
|--------|--------|-----------|-------------|
| **Daily Allowance** | 100-1000 | Daily | Based on role (guest:100, user:500, admin:unlimited) |
| **One-time Grant** | Variable | Once | Welcome bonus for new users |
| **Admin Grant** | Any | Anytime | Manual NUKE allocation |
| **Task Rewards** | Variable | On completion | Completing tutorials, bug reports, etc. |
| **Purchase** | Variable | Anytime | If monetization enabled (future) |

#### NUKE Consumption

| Plan | CPU | Memory | Cost/hour (NUKE) | Daily Allowance Coverage |
|------|-----|--------|-----------------|------------------------|
| `small` | 2 | 4GB | 1 NUKE | 100 hours/day |
| `medium` | 4 | 8GB | 2 NUKE | 50 hours/day |
| `large` | 8 | 16GB | 4 NUKE | 25 hours/day |
| `xlarge` | 16 | 32GB | 8 NUKE | 12.5 hours/day |

#### NUKE Limits & Alerts

```yaml
user_nuke_settings:
  daily_allowance: 500
  max_balance: 5000        # Cap to prevent hoarding
  rollover: false          # Use it or lose it (daily reset)
  alert_thresholds:
    warning: 100           # Alert at 100 NUKE remaining
    critical: 20           # Alert at 20 NUKE remaining
    
server_constraints:
  min_nukes_to_start: 1    # Need at least 1 hour of small plan
  stop_on_depletion: true  # Auto-stop when NUKE runs out
  warn_before_stop: 10     # Warn 10 minutes before auto-stop
```

#### NUKE Ledger

Immutable transaction history:

```python
class NukeTransaction(BaseModel):
    id: UUID
    timestamp: datetime
    user_id: UUID
    amount: int           # Positive = credit, Negative = debit
    balance_after: int
    type: str             # "daily_allowance", "server_usage", "admin_grant", "purchase"
    description: str
    server_id: UUID       # If server usage
    plan_id: UUID         # If server usage
    actor_id: UUID        # Who initiated (system, admin, etc.)
```

#### Resource-Aware Scheduling

With limited hardware, we need smart scheduling:

```
Total Hardware:
  Main Server: 32 CPU, 64GB RAM, 1TB HDD
  Contabo: 6 CPU, 12GB RAM, 200GB SSD
  
Reserved for System:
  - Traefik, FastAPI, PostgreSQL, Redis: ~4 CPU, 8GB RAM
  
Available for User Servers:
  - ~34 CPU, 68GB RAM
  
Smart Scheduling:
  1. Check if requested resources fit
  2. If not, queue the request (FIFO with priority)
  3. Notify user of queue position
  4. Auto-start when resources free up
  5. Respect plan priority (higher plans get priority)
```

### 4.5 User Preferences & Defaults

Users can save default preferences to streamline server spawning.

#### Preference Categories

```yaml
server_defaults:
  environment_id: "uuid"        # Default environment
  plan_id: "uuid"               # Default plan
  custom_resources:             # Optional overrides
    cpu: 4
    memory: "8Gi"
    disk: "100Gi"
  auto_start: false             # Auto-start on login
  idle_timeout: "1h"            # Preferred idle timeout
  
display_preferences:
  theme: "dark"                 # dark, light, system
  language: "en"                # UI language
  timezone: "UTC"               # For scheduling display
  date_format: "YYYY-MM-DD"
  
notification_preferences:
  email_enabled: true
  email_address: "user@example.com"
  notify_on:
    server_ready: true
    server_stopped: true
    low_credits: true
    queue_position: true
    maintenance: true
  
accessibility:
  reduce_motion: false
  high_contrast: false
  font_size: "medium"           # small, medium, large
```

#### User Preferences Model

```python
class UserPreferences(BaseModel):
    user_id: UUID
    
    # Server defaults
    default_environment_id: Optional[UUID]
    default_plan_id: Optional[UUID]
    default_custom_resources: Optional[dict]
    auto_start_servers: bool
    preferred_idle_timeout: str
    
    # Display
    theme: str                    # "dark", "light", "system"
    language: str                 # "en", "es", "fr", etc.
    timezone: str
    
    # Notifications
    email_notifications: bool
    email_address: Optional[str]
    notification_settings: dict   # JSON object for granular control
    
    # Accessibility
    accessibility_settings: dict
    
    updated_at: datetime
```

#### Simplified Spawn Flow

With saved preferences:

```
User clicks "New Server":
  ┌─────────────────────────────┐
  │  Server Spawn Dialog         │
  │                             │
  │  Environment: [my-env ▼]    │ ← Pre-filled from preferences
  │  Plan:        [medium ▼]    │ ← Pre-filled from preferences
  │  Resources:   [4 CPU, 8GB]  │ ← From plan (editable)
  │                             │
  │  [Advanced Options ▼]       │
  │  Duration:    [2 hours]     │
  │  Auto-start:  [✓]           │
  │                             │
  │  Cost: 2 NUKE/hour          │
  │                             │
  │  [Spawn Server] [Save as Default]
  └─────────────────────────────┘
```

#### One-Click Spawn

For power users:
- "Quick Spawn" button uses saved defaults immediately
- Keyboard shortcut: `Ctrl/Cmd + N` for instant spawn with defaults
- Recent servers list for rapid restart

### 4.6 Real-Time Resource Monitoring

#### Global Resource Pool

```yaml
resource_pools:
  main_pool:
    total_cpu: 32
    total_memory: "64Gi"
    total_disk: "1Ti"
    reserved_for_system: "20%"
    
  contabo_pool:
    total_cpu: 6
    total_memory: "12Gi"
    total_disk: "200Gi"
    reserved_for_system: "10%"
    
scheduling_policy:
  default: "best-fit"      # Use server with best fit
  fallback: "queue"        # Queue if no fit
  priority_weighting: true # Higher plans get priority
```

### 4.7 Audit & Compliance

#### Audit Log Schema

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    actor_id UUID REFERENCES users(id),
    actor_username VARCHAR(255),
    actor_role VARCHAR(50),
    action VARCHAR(100),          -- e.g., "user.create", "server.stop"
    target_type VARCHAR(50),      -- "user", "server", "environment"
    target_id UUID,
    target_name VARCHAR(255),
    before_state JSONB,           -- Previous state snapshot
    after_state JSONB,            -- New state snapshot
    ip_address INET,
    user_agent TEXT,
    success BOOLEAN,
    error_message TEXT,
    request_id UUID               -- For tracing
);
```

#### Features

- Every admin/support action logged immutably
- Tamper-evident (append-only, no updates/deletes)
- Searchable by actor, target, action, date range
- Export to CSV, PDF, JSON
- Compliance reports (GDPR, SOC2 ready)

---

## 5. Authentication & Authorization

### 5.1 Dual Auth Strategy

#### Production: NukeHub Auth (OAuth2)

```
User Browser
    │
    ▼
Vite React Frontend
    │
    ▼
NukeHub Auth Login (auth.nukehub.org)
    │
    ▼
JWT Token (signed by NukeHub Auth)
    │
    ▼
FastAPI validates JWT
    │
    ▼
Extract roles from token
    │
    ▼
Check permissions against RBAC
```

#### Development: Local Authentication

```
User Browser
    │
    ▼
React Login Form
    │
    ▼
FastAPI Local Auth Endpoint
    │
    ▼
bcrypt password verification
    │
    ▼
Generate internal JWT
    │
    ▼
Same RBAC system
```

#### Configuration

```env
# Auth mode: "nukehub" | "local"
AUTH_MODE=local

# NukeHub Auth settings (production)
OAUTH_URL=https://auth.nukehub.org
OAUTH_REALM=nukehub
OAUTH_CLIENT_ID=nukelab-platform
OAUTH_CLIENT_SECRET=xxx

# Local auth settings (development)
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_BCRYPT_ROUNDS=12
```

### 5.2 NukeIDE Container Authentication

Each NukeIDE container runs an **nginx proxy** that validates JWT tokens before proxying to Theia.

```
User Request ──► Traefik ──► NukeIDE Container :80
                                    │
                                    ▼
                            ┌───────────────┐
                            │ Nginx Proxy   │
                            │               │
                            │ 1. Extract JWT│
                            │ 2. Validate   │
                            │ 3. Check user │
                            │    matches    │
                            │    container  │
                            │ 4. Add headers│
                            └───────┬───────┘
                                    │
                                    ▼
                            ┌───────────────┐
                            │ Theia Backend │
                            │ Port 3000     │
                            └───────────────┘
```

**Nginx Configuration:**

```nginx
server {
    listen 80;
    
    location / {
        # Validate JWT
        auth_request /auth;
        auth_request_set $auth_user $upstream_http_x_user_id;
        
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-User-Id $auth_user;
    }
    
    location = /auth {
        internal;
        proxy_pass http://fastapi-backend:8000/api/auth/verify;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-Uri $request_uri;
    }
}
```

**Alternative (if nginx auth_request is too slow):**

Validate JWT locally in nginx using Lua + shared secret:

```nginx
# Requires lua-resty-jwt
access_by_lua_block {
    local jwt = require "resty.jwt"
    local token = ngx.var.http_authorization
    local jwt_obj = jwt:verify(os.getenv("JWT_SECRET"), token)
    if not jwt_obj.verified then
        ngx.exit(ngx.HTTP_UNAUTHORIZED)
    end
    ngx.req.set_header("X-User-Id", jwt_obj.payload.sub)
}
```

---

## 6. Data Models

### 6.1 Core Entities

#### User

```python
class User(BaseModel):
    id: UUID
    username: str  # Unique, URL-safe
    email: str
    full_name: str
    role: str  # Reference to Role
    permissions: list[str]  # Override permissions
    groups: list[UUID]  # Organization groups
    
    # Resource quotas
    max_cpu: int
    max_memory: str
    max_disk: str
    max_gpu: int
    max_servers: int
    
    # NUKE Currency
    nuke_balance: int             # Current NUKE balance
    daily_allowance: int          # Daily NUKE allowance
    last_nuke_reset: datetime     # Last daily reset timestamp
    
    # Profile (flexible JSONB - extensible user info)
    profile: dict                 # avatar, timezone, phone, department, organization
    
    # Preferences (app-specific settings)
    preferences: dict             # theme, language, default_environment, default_plan
    
    # Security tracking (audit & protection)
    security: dict                # mfa_enabled, last_ip, failed_attempts, locked_until
    
    # Audit
    login_count: int              # Total successful logins
    last_login: datetime
    last_ip_address: str          # Last login IP
    email_verified_at: datetime   # Email verification timestamp
    
    # Status
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
```

#### Server (User Container)

```python
class Server(BaseModel):
    id: UUID
    name: str
    user_id: UUID
    environment_id: UUID
    plan_id: UUID
    
    # Docker
    container_id: str
    image: str
    status: ServerStatus  # pending, starting, running, stopping, stopped, error
    
    # Resources (from plan, can be overridden)
    allocated_cpu: float
    allocated_memory: str
    allocated_disk: str
    allocated_gpu: int
    
    # Limits (from plan)
    max_runtime: str
    idle_timeout: str
    
    # Networking
    internal_port: int  # Theia port (3000)
    external_url: str   # /user/{username}/{server_id}
    
    # Timestamps
    started_at: datetime
    stopped_at: datetime
    last_activity: datetime
    expires_at: datetime  # Based on max_runtime
    created_at: datetime
```

#### API Token

```python
class ApiToken(BaseModel):
    id: UUID
    user_id: UUID
    name: str                   # "VS Code", "CI/CD", etc.
    token_hash: str             # bcrypt hash of the token
    scopes: list[str]           # ["servers:read", "servers:start"]
    
    # Usage tracking
    last_used_at: datetime
    usage_count: int
    
    # Lifecycle
    created_at: datetime
    expires_at: datetime        # Optional expiration
    revoked_at: datetime        # If manually revoked
    is_active: bool
```

#### Environment Template

```python
class Environment(BaseModel):
    id: UUID
    name: str
    description: str
    image: str
    
    # Resource defaults
    default_cpu: int
    default_memory: str
    default_disk: str
    default_gpu: int
    
    # Limits
    max_cpu: int
    max_memory: str
    max_disk: str
    max_gpu: int
    
    # Configuration
    startup_script: str
    env_vars: dict[str, str]
    volumes: list[str]
    
    # Metadata
    is_active: bool
    is_public: bool
    created_by: UUID
    created_at: datetime
```

#### Plan (Resource Tier)

```python
class Plan(BaseModel):
    id: UUID
    name: str  # e.g., "small", "medium", "large"
    description: str
    
    # Resources
    cpu: float  # Whole CPUs only (2, 4, 8, 16)
    memory: str  # e.g., "8Gi"
    disk: str    # e.g., "100Gi"
    gpu: int
    
    # Features
    max_runtime: str     # e.g., "24h"
    idle_timeout: str    # e.g., "1h"
    allow_scheduling: bool
    allow_snapshots: bool
    priority: str        # "low", "normal", "high"
    
    # Restrictions
    min_role: str        # Minimum role required
    max_per_user: int    # Max servers per user with this plan
    requires_approval: bool
    
    # Metadata
    is_active: bool
    is_default: bool     # Default plan for new users
    display_order: int
    created_at: datetime
    updated_at: datetime
```

#### User Preferences

```python
class UserPreferences(BaseModel):
    user_id: UUID
    
    # Server defaults
    default_environment_id: Optional[UUID]
    default_plan_id: Optional[UUID]
    default_custom_resources: Optional[dict]
    auto_start_servers: bool = False
    preferred_idle_timeout: str = "1h"
    
    # Display
    theme: str = "system"         # "dark", "light", "system"
    language: str = "en"          # "en", "es", "fr", etc.
    timezone: str = "UTC"
    
    # Notifications
    email_notifications: bool = True
    email_address: Optional[str]
    notification_settings: dict = {}  # Granular notification control
    
    # Accessibility
    accessibility_settings: dict = {}
    
    updated_at: datetime
```

#### Audit Log

```python
class AuditLog(BaseModel):
    id: UUID
    timestamp: datetime
    actor_id: UUID
    actor_username: str
    actor_role: str
    action: str
    target_type: str
    target_id: UUID
    target_name: str
    before_state: dict
    after_state: dict
    ip_address: str
    user_agent: str
    success: bool
    error_message: str
```

#### Credit Transaction

```python
class CreditTransaction(BaseModel):
    id: UUID
    timestamp: datetime
    user_id: UUID
    amount: int              # Positive = credit, Negative = debit
    balance_after: int
    type: str                # "daily_allowance", "server_usage", "admin_grant", "purchase", "refund"
    description: str
    server_id: UUID          # If related to server usage
    plan_id: UUID            # If related to plan
    actor_id: UUID           # Who initiated (system, admin, user)
    metadata: dict           # Additional context
```

### 6.2 Database Schema

See `backend/database/schema.sql` for full schema with indexes, constraints, and foreign keys.

---

## 7. API Design

### 7.1 REST Endpoints

#### Authentication

```
POST   /api/auth/login              # Local login
POST   /api/auth/logout             # Logout
POST   /api/auth/refresh            # Refresh token
GET    /api/auth/me                 # Current user
POST   /api/auth/oauth/callback     # NukeHub Auth OAuth callback
```

#### API Tokens

```
GET    /api/tokens                  # List user's API tokens
POST   /api/tokens                  # Create new token (returns token once)
GET    /api/tokens/{id}             # Get token details (without hash)
DELETE /api/tokens/{id}             # Revoke token
POST   /api/tokens/{id}/regenerate  # Regenerate token
GET    /api/tokens/{id}/usage       # Get token usage statistics
```

**Token Authentication:**
```
Authorization: Token <api-token>
```

#### Users

```
GET    /api/users                   # List users (paginated, filterable)
POST   /api/users                   # Create user
GET    /api/users/{id}              # Get user
PUT    /api/users/{id}              # Update user
DELETE /api/users/{id}              # Delete user
POST   /api/users/{id}/disable      # Disable/enable user
POST   /api/users/{id}/impersonate  # Impersonate user (super_admin only)
GET    /api/users/{id}/servers      # Get user's servers
GET    /api/users/{id}/resources    # Get user's resource usage
GET    /api/users/{id}/preferences  # Get user preferences
PUT    /api/users/{id}/preferences  # Update user preferences
POST   /api/users/{id}/preferences/reset  # Reset to defaults
```

#### Servers

```
GET    /api/servers                 # List servers (filterable by user, status)
POST   /api/servers                 # Spawn new server
GET    /api/servers/{id}            # Get server details
POST   /api/servers/{id}/start      # Start server
POST   /api/servers/{id}/stop       # Stop server
POST   /api/servers/{id}/restart    # Restart server
DELETE /api/servers/{id}            # Delete server
GET    /api/servers/{id}/logs       # Get server logs
GET    /api/servers/{id}/metrics    # Get current metrics
```

#### Environments

```
GET    /api/environments            # List environments
POST   /api/environments            # Create environment
GET    /api/environments/{id}       # Get environment
PUT    /api/environments/{id}       # Update environment
DELETE /api/environments/{id}       # Delete environment
```

#### Plans

```
GET    /api/plans                   # List available plans
POST   /api/plans                   # Create plan (admin)
GET    /api/plans/{id}              # Get plan details
PUT    /api/plans/{id}              # Update plan (admin)
DELETE /api/plans/{id}              # Delete plan (admin)
GET    /api/plans/{id}/users        # Get users on this plan
POST   /api/users/{id}/plan         # Assign custom plan to user
```

#### NUKE Currency

```
GET    /api/credits/balance          # Get current NUKE balance
GET    /api/credits/transactions      # Get NUKE transaction history
POST   /api/credits/grant            # Grant NUKE (admin)
POST   /api/credits/deduct           # Deduct NUKE (admin)
GET    /api/credits/usage            # Get NUKE usage statistics
POST   /api/credits/reset-daily      # Trigger daily NUKE reset (system)
```

#### Monitoring

```
GET    /api/metrics/global           # Global resource usage
GET    /api/metrics/users            # Per-user resource usage
GET    /api/metrics/servers/{id}     # Per-server metrics history
WS     /api/metrics/stream           # WebSocket real-time metrics stream
```

#### Audit

```
GET    /api/audit/logs              # Query audit logs
POST   /api/audit/export            # Export audit logs
GET    /api/audit/stats             # Audit statistics
```

#### Admin Workspaces

```
GET    /api/admin/workspaces              # List all workspaces
GET    /api/admin/workspaces/{id}         # Get workspace details
PUT    /api/admin/workspaces/{id}         # Update workspace
DELETE /api/admin/workspaces/{id}         # Delete workspace
POST   /api/admin/workspaces/bulk-action  # Bulk delete/activate/deactivate
GET    /api/admin/workspaces/{id}/members  # List workspace members
GET    /api/admin/workspaces/{id}/volumes  # List workspace volumes
```

#### Admin Volumes

```
GET    /api/admin/volumes              # List all volumes
GET    /api/admin/volumes/{id}         # Get volume details
PUT    /api/admin/volumes/{id}         # Update volume
DELETE /api/admin/volumes/{id}         # Delete volume
POST   /api/admin/volumes/bulk-action  # Bulk delete/activate/archive
```

#### Bulk Operations

```
POST   /api/bulk/servers/bulk-action      # Bulk start/stop/restart/delete servers (JWT only)
POST   /api/admin/workspaces/bulk-action  # Bulk delete/activate/deactivate workspaces (JWT only)
POST   /api/admin/volumes/bulk-action     # Bulk delete/activate/archive volumes (JWT only)
POST   /api/admin/users/bulk-action       # Bulk disable/enable/delete users (JWT only)
POST   /api/admin/servers/bulk-action     # Bulk start/stop/delete servers (admin, JWT only)
```

#### System

```
GET    /api/system/health           # Health check
GET    /api/system/config           # Get platform config
PUT    /api/system/config           # Update platform config
POST   /api/system/maintenance      # Toggle maintenance mode
GET    /api/system/stats            # Platform statistics
```

### 7.2 WebSocket Events

#### Server Status Updates

```json
{
  "event": "server.status_changed",
  "data": {
    "server_id": "uuid",
    "user_id": "uuid",
    "status": "running",
    "timestamp": "2026-04-27T12:00:00Z"
  }
}
```

#### Real-Time Metrics

```json
{
  "event": "metrics.server",
  "data": {
    "server_id": "uuid",
    "cpu_percent": 45.2,
    "memory_used": "2.4Gi",
    "memory_total": "8Gi",
    "disk_used": "12Gi",
    "disk_total": "50Gi",
    "network_rx": "1.2MB/s",
    "network_tx": "0.8MB/s",
    "timestamp": "2026-04-27T12:00:00Z"
  }
}
```

#### Admin Notifications

```json
{
  "event": "admin.notification",
  "data": {
    "type": "quota_exceeded",
    "severity": "warning",
    "user_id": "uuid",
    "message": "User has exceeded CPU quota",
    "timestamp": "2026-04-27T12:00:00Z"
  }
}
```

---

## 8. Implementation Phases

### Phase 1: Foundation & Scaffolding (Weeks 1-3)

**Goal**: Project structure, auth, basic container spawning

#### Tasks

- [x] **Project Structure**
  - [x] Initialize monorepo structure
  - [x] `frontend/` — Vite + React 19 with TypeScript, Tailwind, shadcn/ui
  - [x] `backend/` — FastAPI with asyncpg, Pydantic, Docker SDK
  - [x] `database/` — PostgreSQL 18 schema and migrations
  - [x] `environments/` — Environment Dockerfiles
  - [x] `compose.yml` — Full stack orchestration
  - [x] `infrastructure/traefik/` — Traefik configuration

- [x] **Database Setup**
  - [x] Create PostgreSQL 18 schema (users, roles, permissions, servers, environments, audit_logs)
  - [x] Set up migration system (Alembic)
  - [x] Seed default roles and super_admin user
  - [x] Create indexes for common queries

- [x] **Redis Setup**
  - [x] Configure Redis for sessions
  - [x] Configure Redis for pub/sub
  - [x] Configure Redis for Celery broker

- [x] **Authentication System**
  - [x] Local auth: bcrypt password hashing, JWT generation
  - [x] NukeHub Auth: OAuth2 flow, JWT validation
  - [x] Auth middleware for FastAPI
  - [x] Permission checking decorators
  - [x] Role-based route guards

- [x] **NukeIDE Containerization**
  - [x] Create `environments/dev/Dockerfile`
    - [x] Base: Debian 13 or Ubuntu 24.04
    - [x] Install Node.js 22
    - [x] Build NukeIDE (clone from nuke-ide repo)
    - [x] Install nginx
    - [x] Add nginx auth proxy config
    - [x] Add startup script
  - [x] Update `environments/default/Dockerfile`
    - [x] Same structure as dev but with nuclear tools
    - [x] Keep existing tool installations
    - [x] Add nginx auth proxy

- [x] **Container Spawning**
  - [x] Docker SDK integration (async)
  - [x] Server spawn endpoint (`POST /api/servers`)
  - [x] Container lifecycle management (start, stop, delete)
  - [x] Traefik dynamic routing labels
  - [x] Volume creation and mounting

- [x] **Basic Frontend**
  - [x] Login page (local auth mode)
  - [x] Dashboard shell with sidebar navigation
  - [x] User profile page
  - [x] Server list page (basic)
  - [x] Server spawn form (environment selection)

- [x] **Traefik Configuration**
  - [x] Dynamic Docker provider
  - [x] Route: `/app/*` → Vite SPA (static files served by Nginx)
  - [x] Route: `/api/*` → FastAPI
  - [x] Route: `/user/{username}` → user containers
  - [x] WebSocket upgrade handling
  - [x] Basic rate limiting

#### Deliverables

- [x] Admin can log in via local auth
- [x] Admin can spawn a NukeIDE container
- [x] Admin can access NukeIDE via browser
- [x] Basic dashboard UI functional
- [x] All services running via compose

#### Success Criteria

```gherkin
Given I am an admin user
When I log in with username and password
Then I see the admin dashboard

Given I am on the dashboard
When I click "New Server" and select "dev" environment
Then a NukeIDE container starts
And I can access it at /user/admin/dev-server-1

Given I have a running server
When I click "Stop"
Then the container stops gracefully
```

---

### Phase 2: User Management & RBAC (Weeks 4-6)

**Goal**: Complete user lifecycle management with granular permissions

#### Tasks

- [x] **RBAC Implementation**
  - [x] Role model with permission matrix
  - [x] Permission checking middleware
  - [x] Route-level permission decorators
  - [x] Frontend permission hooks/components

- [x] **User CRUD**
  - [x] Create user (admin/moderator)
  - [x] Read user list with filters (role, status, search)
  - [x] Update user (profile, role, quotas)
  - [x] Delete/disable user
  - [x] Bulk operations (servers, workspaces, volumes)

- [x] **User Profile**
  - [x] View own profile
  - [x] Edit own profile
  - [x] Change password
  - [x] View own servers and usage

- [x] **User Preferences**
  - [x] Preferences model (defaults, display, notifications)
  - [x] Preferences API (get, update, reset)
  - [x] Settings page UI
  - [x] Default environment/plan selection
  - [x] Theme/language/timezone settings
  - [x] Notification preferences
  - [x] Quick spawn with saved defaults (`Alt+N`)

- [x] **NUKE Currency System**
  - [x] NUKE balance model and ledger
  - [x] Daily allowance system (automated reset)
  - [x] NUKE consumption on server usage (auto-billing via Celery)
  - [x] NUKE grant/deduct (admin)
  - [x] Low NUKE alerts and auto-stop on credit depletion
  - [x] NUKE transaction history

- [x] **Admin Dashboard**
  - [x] User management table
  - [x] Role assignment UI
  - [x] Permission matrix editor
  - [x] User activity timeline (`/activity` route with filters)
  - [x] Credit management (grant/deduct/view)
  - [x] Server management table
  - [x] Bulk actions (start/stop/restart/delete servers, activate/deactivate/delete workspaces, activate/archive/delete volumes)

- [x] **Server Lifecycle**
  - [x] Start/stop/restart/delete servers (API ready, UI basic)
  - [x] Credit check before start
  - [x] Server status polling
  - [x] Server logs viewer
  - [x] Server detail page

#### Deliverables

- [x] Admin can create users with specific roles
- [x] Permission system prevents unauthorized actions
- [x] Admin dashboard shows all users and servers
- [x] Users can manage own profile and servers

#### Success Criteria

```gherkin
Given I am an admin
When I create a new user with role "moderator"
Then the user can log in
And the user receives 500 daily NUKE
And the user can create other users
But the user cannot access other users' servers

Given I am a regular user
When I try to access admin dashboard
Then I get a 403 Forbidden error

Given I have 1 NUKE remaining
When I try to start a server costing 2 NUKE/hour
Then I get an error: "Insufficient NUKE"
```

---

### Phase 3: Environment Templates & Resource Management (Weeks 7-9)

**Goal**: Multiple environments, resource quotas, and limits

#### Tasks

- [x] **Environment Template System**
  - [x] Environment CRUD API
  - [x] Environment builder UI (admin)
  - [ ] Environment selection in spawn form (Phase 5)
  - [x] Environment-specific branding
  - [x] Environment activation/deactivation

- [x] **Server Plans**
  - [x] Plan CRUD API (admin)
  - [x] Plan builder UI (admin)
  - [x] Plan selection in spawn form
  - [x] Plan restrictions enforcement (role, approval)
  - [x] Custom plans per user (admin override via UserPlanAccess)
  - [x] Plan usage tracking (analytics dashboard)

- [x] **Resource Quotas**
  - [x] Quota model (per-user)
  - [x] Quota enforcement on spawn
  - [x] Quota usage tracking
  - [x] Quota exceeded alerts

- [x] **Resource Limits**
  - [x] Docker container limits (CPU, memory) from plan
  - [x] Disk quota enforcement (spawn-time, partial: standalone volume creation gap)
  - [ ] GPU allocation (if available) (future)
  - [x] Limit overrides for admins (via custom plans)

- [x] **Hardware Resource Scheduling**
  - [x] Global resource pool tracking (ResourcePoolService)
  - [x] Resource availability check before spawn
  - [x] Queue system when resources unavailable
  - [x] Priority-based scheduling (plan priority)
  - [ ] Server migration between hosts (future)
  - [x] Auto-stop idle servers to free resources

- [x] **Volume Management**
  - [x] Persistent user volumes
  - [x] Shared workspace volumes
  - [x] Volume backup/restore (BackupService with retention)
  - [x] Volume quota enforcement (mounted volumes, gap: standalone creation)

- [ ] **Environment Images**
  - [ ] Build system for environment images (future)
  - [ ] Image registry integration (future)
  - [ ] Image versioning (future)
  - [ ] Base image updates (future)

#### Deliverables

- [x] Admin can create custom environment templates (Docker image, packages, env vars, ports)
- [x] Multiple plans available (small, medium, large, xlarge)
  - [x] Users can choose environment AND plan when spawning
  - [x] Resource quotas enforced per plan
  - [x] Admin can create/modify environments and plans

#### Success Criteria

```gherkin
Given I am a user
When I spawn a server with an environment template and "small" plan
Then the container has the environment's configured tools installed
And the container has 2 CPU and 4GB RAM allocated

Given I am a user
When I spawn a server with an environment template and "large" plan
Then the container has the environment's configured tools installed
And the container has 8 CPU and 16GB RAM allocated

Given I have reached my server limit for "small" plan (max_per_user=3)
When I try to spawn a 4th "small" server
Then I get an error: "Plan limit reached for small"
```

---

### Phase 4: Real-Time Monitoring Dashboard (Weeks 10-12)

**Goal**: Live resource monitoring, historical data, and alerting
**Status**: Complete

#### Tasks

- [x] **Metrics Collection**
  - [x] Docker Stats API integration (async streaming)
  - [x] Custom metrics collector (CPU, memory, disk, network)
  - [ ] GPU metrics (nvidia-smi integration) *[Future]*
  - [x] Metrics storage in PostgreSQL (time-series)

- [x] **WebSocket Streaming**
  - [x] WebSocket endpoint for real-time metrics
  - [x] Subscription model (subscribe to specific servers/users)
  - [x] Efficient data serialization (JSON) *[MessagePack deferred]*
  - [x] Connection management and cleanup
  - [x] Redis pub/sub for broadcasting

- [x] **Monitoring Dashboard**
  - [x] Global resource overview (all users/servers)
  - [x] Per-user resource usage page
  - [x] Per-server real-time charts
  - [x] Top consumers leaderboard
  - [x] Resource usage trends (7d, 30d, 90d)

- [x] **Alerting System**
  - [x] Alert rules (quota thresholds, container crashes)
  - [x] Alert rule API CRUD
  - [x] Email notifications (SMTP integration)
  - [x] In-app notifications
  - [x] Alert history and acknowledgment

- [x] **Health Checks**
  - [x] Container health checks
  - [x] Auto-restart on failure (rate-limited)
  - [x] Unhealthy server notifications
  - [x] System health dashboard (Postgres, Redis, Docker)

#### Deliverables

- [x] Real-time monitoring dashboard with live charts
- [x] Admin can see all users' resource usage
- [x] Users can see own usage
- [x] Alert rules API ready (needs seeding and UI)

#### Success Criteria

```gherkin
Given a server is running
When I open the monitoring dashboard
Then I see CPU and memory usage updating every second
```

---

### Phase 5: Advanced Platform Features (Weeks 13-16)

**Goal**: Industrial-grade features for production use
**Status**: ~95% Complete — All high-priority items done; remaining work is medium/low priority hardening and test coverage

---

#### Completed ✅

The following features are fully implemented and in active use:

- **[x] Audit Logging** — Middleware auto-logs all state-changing requests; viewer with filters at `/admin/audit-logs`; CSV/JSON export
- **[x] Server Scheduling** — Cron-based schedules with visual builder UI; timezone support; Celery task for execution
- **[x] API Keys** — Scoped token generation (24 scopes); management UI; usage tracking; revocation/expiration
- **[x] Shared Workspaces** — Workspace CRUD; member/invitation management; volume associations; grid/list UI
- **[x] Notifications** — 20+ notification types; email + in-app + webhook delivery; WebSocket real-time; preferences UI
- **[x] Maintenance Mode** — Toggle with graceful draining; dedicated `/maintenance` page; admin settings panel
- **[x] Rate Limiting (Two-Layer)** — Traefik DDoS protection (10K/min per IP) + FastAPI per-user Redis-backed throttling (role-based tiers: guest 30/min → super_admin ∞)
- **[x] Backup & Restore** — Database backup (`./nukelabctl backup`); volume backup service with retention policy
- **[x] Health Checks** — Container health monitoring; auto-restart with rate limiting; system health dashboard
- **[x] Bulk Operations** — Server start/stop/restart/delete; workspace activate/deactivate/delete; volume activate/archive/delete
- **[x] Quick Spawn** — `Alt+N` opens deploy dialog pre-filled with saved user preferences
- **[x] User Activity Timeline** — `/activity` route with paginated table, filters, and detail drawer
- **[x] NUKE Consumption** — Auto-billing via Celery; low-balance alerts; auto-stop on depletion
- **[x] Custom Plans Per User** — `UserPlanAccess` model; admin grant/revoke endpoints
- **[x] Resource Pool Tracking** — Global CPU/RAM/disk tracking; queue position logic

---

#### Remaining Work 🚧

| Priority | Task | Notes |
|----------|------|-------|
| **High** | ~~Fix schedule API bug~~ ✅ | `request` → `body` in `schedules.py` create/update endpoints |
| **High** | ~~Broaden rate limiting~~ ✅ | Added to auth refresh (10/min), server spawn (10/min), all bulk actions (20/min) |
| **High** | ~~Volume quota gap~~ ✅ | `recalculate_usage()` now counts volume sizes; `check_volume_creation_allowed()` enforces quota on `POST /api/volumes/` |
| **Medium** | ~~Bulk action test coverage~~ ✅ | `test_bulk.py` now has 12 mocked spawner lifecycle tests (start/stop/restart/delete, mixed results, cross-user, not-found) |
| **Medium** | ~~Frontend health monitoring UI~~ ✅ | Admin health monitoring page at `/admin/health` with system services, resource gauges, container health table, and auto-restart events |
| **Medium** | ~~Traefik rate limiting~~ ✅ | Two-layer architecture: Traefik DDoS-only (10K/min) + FastAPI per-user Redis throttling; `test_rate_limiting.py` with 14 tests |
| **Low** | ~~IP allowlist/blocklist~~ ✅ | Full middleware + admin CRUD API + UI with CIDR support; 24 tests |
| **Low** | ~~Security headers~~ ✅ | Exception-safe ASGI middleware + Traefik layer; CSP, Cache-Control, Clear-Site-Data, HSTS, CORP; 10 tests |
| **Low** | ~~Scheduled maintenance windows~~ ✅ | `MaintenanceWindow` model + admin CRUD API + Celery task; auto enable/disable + advance user notification; 27 tests |

---

#### Known Bugs / Tech Debt 🔧

| Issue | Location | Impact |
|-------|----------|--------|
| ~~`test_bulk.py` thin coverage~~ ✅ | `backend/tests/test_bulk.py` | 12 mocked spawner lifecycle tests added |

---

#### Deliverables

- [x] Complete audit trail for all actions (viewer + export)
- [x] Server scheduling system (cron + UI + execution)
- [x] API key management (scoped tokens + UI)
- [x] Shared workspaces (members + volumes + UI)
- [x] Advanced notifications (20+ types + multi-channel)
- [x] Schedule API bug fixed and tested
- [x] Rate limiting covers auth refresh, server spawn, and all bulk actions
- [x] Volume quota enforced on standalone volume creation
- [x] Bulk action tests with mocked spawner execution
- [x] IP allowlist/blocklist middleware with CIDR support, admin UI, and self-block prevention
- [x] Quota service disk calculation fixed (no double-counting)
- [x] Volume max size validation shared between user and admin endpoints
- [x] Admin volume edit dialog uses GB slider with min-bound enforcement

---

#### Success Criteria

```gherkin
Given I am an admin
When I create a cron schedule for a server
Then the schedule is saved and the API returns 200

Given a schedule is due
When the Celery worker evaluates schedules
Then the server action executes automatically

Given a user with a full disk quota
When they try to create a standalone volume
Then the request is rejected with 422

Given a running server
When I bulk-select it and click "Stop"
Then the server stops and the bulk API returns success
```

---

### Phase 6: Production Hardening & Kubernetes (Future)

**Goal**: Production readiness and Kubernetes migration
**Priority**: Low — Platform is feature-complete on Docker/Podman. Kubernetes support is a future scalability goal, not a near-term requirement.

#### Tasks

- [ ] **Testing**
  - [ ] Unit tests (backend >80% coverage)
  - [ ] Integration tests (API endpoints)
  - [ ] E2E tests (Playwright)
  - [x] Load testing (Locust/k6) — Phase 8 delivered: Locust/k6 hybrid, 5 profiles, PgBouncer connection flood
  - [x] Dedicated backend test image — `backend/Dockerfile` `target=test` with dev deps pre-installed; `./nukelabctl test backend` uses `backend-test` service

- [ ] **Security**
  - [x] OWASP Top 10 audit — documented in `docs/OWASP-AUDIT.md`; overall rating: Pass
  - [x] Dependency scanning — Dependabot configured (`.github/dependabot.yml`); `pip-audit`, `npm audit`, and `bandit` integrated via `./nukelabctl security`; production dependencies cleared of known CVEs
  - [ ] Secret management (HashiCorp Vault or Sealed Secrets)
  - [x] Security headers (HSTS, CSP, X-Frame-Options, CORP, Permissions-Policy) — exception-safe ASGI middleware
  - [x] Path traversal prevention — centralized `secure_path()` with `Path.resolve()` + `relative_to()`
  - [x] Production secret validation — refuses to start with default secrets
  - [x] CSRF protection — double-submit cookie pattern with smart exemptions
  - [x] Removed harmful `browserXssFilter`
  - [ ] Penetration testing

- [ ] **Performance**
  - [x] Database connection pooling — `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `pool_pre_ping` wired into `create_async_engine`; asyncpg `command_timeout` for query abort
  - [x] Redis response caching — msgpack serialization, circuit breaker, stampede protection, SET-based invalidation; server list + admin list endpoints; 30s TTL with proactive invalidation
  - [x] Database query optimization — `db_profiler.py`, `tune_autovacuum.py`, `app/services/query_stats.py`, slow-query SQLAlchemy event listener, and model indexes
  - [ ] CDN for static assets
  - [x] PgBouncer setup — transaction mode, auto-overlay, 20k client conn

- [ ] **Observability**
  - [x] Structured logging (JSON) — `app.core.logging` with `JSONFormatter`, `CorrelationIdFilter`, correlation ID propagation
  - [x] Custom HTTP request metrics — `RequestMetric` model, route-aware normalization, batched DB writes, admin dashboard
  - [x] Prometheus metrics export — `app/core/prometheus_metrics.py`, `/api/metrics` endpoint, request counter, WebSocket/Redis-cache/business gauges, multiprocess support
  - [x] Grafana dashboards — provisioned dashboards (`nukelab-api.json`, `nukelab-infrastructure.json`) with Prometheus datasource; exporters for Postgres, Redis, Celery, Node, PgBouncer
  - [x] Distributed tracing (OpenTelemetry) — OTLP exporter, Jaeger UI, FastAPI/Celery/SQLAlchemy/Redis auto-instrumentation
  - [x] Error tracking (Sentry) — backend (`app/core/sentry.py`) with FastAPI/Celery/SQLAlchemy/Redis integrations and PII scrubbing; frontend (`@sentry/react`) captures server errors

- [ ] **Kubernetes**
  - [ ] Kubernetes manifests (Deployments, Services, Ingress)
  - [ ] Helm chart
  - [ ] Horizontal Pod Autoscaler
  - [ ] Persistent Volume Claims
  - [ ] ConfigMaps and Secrets
  - [ ] Network Policies
  - [ ] Pod Security Standards

- [x] **Deployment**
  - [x] CI/CD pipeline (GitHub Actions) — lint/test/build/push to ghcr.io, path-filtered, branch/tag image tagging
  - [ ] Blue-green deployment
  - [ ] Database migration strategy
  - [ ] Rollback procedures
  - [ ] Monitoring and alerting

#### Deliverables

- [ ] Production-ready platform with comprehensive testing
  - [ ] Kubernetes deployment manifests
  - [ ] Monitoring and observability stack
  - [ ] Security audit passed

#### Success Criteria

```gherkin
Given the platform is deployed in Kubernetes
When 100 users spawn servers simultaneously
Then all servers start within 30 seconds
And the API remains responsive

Given a security vulnerability is found
When a patch is deployed
Then the deployment completes with zero downtime
```

---

### Phase 7: Production Hardening — Quick Wins (Weeks 17-18)

**Goal**: Industrial-grade improvements that can be done in parallel or before Phase 6
**Priority**: High — addresses reliability and observability gaps

#### Tasks

- [x] **Observability — Structured Logging**
  - [x] Add correlation IDs to all requests (`contextvars` + middleware)
  - [x] JSON-structured logging format (`JSONFormatter` + `TextFormatter`)
  - [x] Request ID tracking middleware (`CorrelationIdFilter`, `app.core.context.correlation_id`)
  - [x] `print()` → `logger.*` migration (~46 replacements across 12 files)
  - [x] Celery cross-thread correlation ID propagation via Redis headers
  - [x] Audit middleware populates `ActivityLog.request_id` from contextvar

- [x] **Observability — HTTP Request Metrics**
  - [x] `RequestMetric` model with p50/p95/p99 aggregation
  - [x] Route-aware path normalization (reads FastAPI route regexes at startup)
  - [x] Batched fire-and-forget DB writes (100 records / 5s flush)
  - [x] `GET /api/metrics/requests` admin-only endpoint with percentile aggregation
  - [x] Frontend "API Performance" dashboard section (`/admin/analytics`)
  - [x] 30-day retention via `cleanup_expired_data` Celery task
  - [ ] Prometheus metrics export (deferred — custom pipeline sufficient for single-node)

- [x] **Reliability — Graceful Shutdown**
  - [x] Handle SIGTERM properly (Uvicorn lifespan shutdown hook)
  - [x] Wait for in-flight requests (Uvicorn default + background task cancellation with 3s timeout)
  - [x] Drain WebSocket connections (parallel `asyncio.gather`, code 1001, 3s timeout)
  - [x] Flush pending request metrics buffer on shutdown (5s timeout, yields for fire-and-forget stragglers)
  - [x] Stop Redis listener and close Redis client (3s timeout)
  - [x] Dispose database engine (async pool close, 3s timeout)
  - [x] `ShutdownCoordinator` with structured shutdown logging and elapsed-time tracking
  - [x] Draining health endpoint — `/health` returns 503 as soon as shutdown starts (Traefik pre-drain)
  - [x] Docker `stop_grace_period` — 30s backend, 20s celery-worker/beat (prevents premature SIGKILL)

- [x] **Security — Input Validation**
  - [x] Request size limits — ASGI middleware `RequestSizeLimitMiddleware` (10 MB default, configurable, 413 on overflow, wraps receive for chunked transfers)
  - [x] Strict CORS for production — explicit origin whitelist, restricted methods/headers, preflight caching, validated at startup (rejects `*` in production)
  - [x] Security headers (HSTS, CSP) — `security-headers@file` and `csp-header@file` middlewares deployed in Traefik dynamic config
  - [x] CSRF protection — double-submit cookie pattern with smart exemptions
  - [x] IP allowlist/blocklist middleware with CIDR support, admin CRUD API, and UI
  - [x] Redis response caching — msgpack + circuit breaker + stampede protection + SET-based invalidation

- [x] **Database — Connection Pooling & Timeouts**
  - [x] SQLAlchemy `pool_recycle=3600` — stale connection recycling
  - [x] SQLAlchemy `pool_pre_ping=True` — validate connections before checkout
  - [x] asyncpg `command_timeout` — query-level timeout (default 30s)
  - [x] Fixed dead config: `max_overflow` and `pool_timeout` were defined but never passed to `create_async_engine`
  - [x] PgBouncer setup — `DATABASE_PGBOUNCER_URL` architecture, auto-overlay via `nukelabctl`, NullPool, TCP keepalive, ulimits, healthcheck
  - [x] Proper index usage — indexes added on `request_metrics` (path, status_code, user_id, correlation_id, created_at)

- [x] **Rate Limiting**
  - [x] Per-user rate limiting (FastAPI + Redis, JWT-based, role tiers)
  - [x] Global DDoS protection at Traefik level (10K/min per IP)
  - [x] WebSocket message-level throttling (120/min per user)
  - [x] 14 tests covering all tiers, expired JWT, Redis fail-open, strict endpoints

- [x] **Redis Response Caching**
  - [x] Shared Redis client singleton (`app.core.redis_client`) — replaces ~15 ad-hoc `redis.from_url()` calls
  - [x] `app.core.cache` utility — msgpack serialization (faster + more compact than JSON), base64-safe storage with `decode_responses=True`
  - [x] Circuit breaker — in-memory `_CacheCircuitBreaker` with CLOSED/OPEN/HALF_OPEN states; 5-failure threshold, 30s recovery timeout; prevents hammering degraded Redis
  - [x] Stampede protection — `cache_get_or_set` with Redis `SET NX EX` lock; only one coroutine rebuilds; waiters poll and retry
  - [x] SET-based invalidation — `cache_track_key` + `cache_delete_tracked` using Redis SETs for O(M) deletion instead of O(N) SCAN
  - [x] Server list caching — `GET /servers/` cached per-user (30s TTL); `GET /admin/servers` cached per query params (30s TTL)
  - [x] Complete invalidation — all 8 mutation paths invalidate: create, start, stop, restart, delete, update, bulk-action, ping-activity
  - [x] Fail-safe — Redis errors logged and treated as cache misses; never returns 500 due to cache failure
  - [x] 32 tests covering serialization, all primitives, stampede protection, SET tracking, circuit breaker states

#### Status: Complete ✅ — All Phase 7 quick wins delivered; graceful shutdown, request size limits, strict CORS, structured logging, HTTP metrics, connection pooling, Redis response caching, and PgBouncer all implemented and tested

---

### Phase 8: Load Testing & Performance Validation

**Goal**: Prove the platform handles 100k-user scale before moving to multi-node infrastructure
**Priority**: High — required before claiming production readiness for large user bases
**Status**: Delivered ✅

#### Overview

A hybrid load testing setup using **Locust** (realistic user behavior, Python) and **k6**
(high-RPS endpoint stress testing, Go runtime). This covers two complementary needs:
Locust models real user flows (login → browse → spawn → stop), while k6 finds the
absolute RPS breaking point of individual endpoints.

#### Deliverables

**Infrastructure**
- `backend/tests/load/locustfile.py` — Locust scenarios: AnonymousUser, RegularUser, AdminUser, ConnectionFloodUser
- `backend/tests/load/k6/api-stress.js` — k6 scripts: smoke, baseline, stress, spike, endurance profiles
- `backend/tests/load/setup_test_data.py` — Pre-seeds 100+ test users directly in DB (bypasses API rate limits)
- `compose.loadtest.yml` — Docker Compose overlay for Locust (port 8089) and k6 containers
- `scripts/run-load-tests.sh` — One-command runner for all profiles with automatic test-data verification
- `backend/requirements-loadtest.txt` — Locust dependency (isolated from main requirements)

**Test Profiles**

| Tool | Profile | Load | Duration | Purpose |
|------|---------|------|----------|---------|
| Locust | smoke | 1 user | 60s | Verify system works |
| Locust | baseline | 50 users | 5m | Normal production traffic |
| Locust | stress | 500 users | 10m | Find breaking point |
| Locust | spike | 300 users | 5m | Sudden traffic surge |
| Locust | endurance | 50 users | 30m | Memory leak detection |
| Locust | connection | 1000 idle users | 5m | PgBouncer connection stress |
| k6 | smoke | 10 VUs | 30s | Minimal endpoint check |
| k6 | baseline | 100 VUs | 5m | High-RPS sustained load |
| k6 | stress | 500 VUs | 10m | Absolute breaking point |
| k6 | spike | 10→500 VUs | 5m | Instant surge capacity |
| k6 | endurance | 100 VUs | 30m | Long-term stability |

**Key Design Decisions**

1. **`DATABASE_PGBOUNCER_URL` auto-detection** — Load tests go through Traefik just like real users, hitting the full stack including PgBouncer when enabled.
2. **ConnectionFloodUser** — A special Locust class that logs in and then stays nearly idle, stress-testing PgBouncer's ability to handle thousands of concurrent idle client connections.
3. **Self-seeding test data** — `setup_test_data.py` creates users directly via SQLAlchemy, avoiding the 5/min registration rate limit that would skew load test results.
4. **Controlled spawn/stop rates** — Container lifecycle endpoints (spawn, start, stop) have low weights (1-2) to avoid overwhelming the Docker daemon, which is a separate bottleneck from API/DB throughput.

**Operational Playbook**

During a load test, monitor these in parallel:

```bash
# PgBouncer pool saturation (cl_waiting should be 0)
./nukelabctl exec pgbouncer psql -p 6432 pgbouncer -U nukelab -c "SHOW POOLS;"

# Postgres connection states
./nukelabctl exec postgres psql -U nukelab -c \
  "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"

# Slow queries under load
./nukelabctl exec backend python scripts/db_profiler.py slow-queries --limit 10

# Container resource usage
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

**Success Criteria**

```gherkin
Given 500 concurrent simulated users
When the Locust stress test runs for 10 minutes
Then p95 latency stays below 1000ms
And error rate stays below 5%
And PgBouncer cl_waiting remains at 0
And Postgres active connections stay below 400

Given 1000 idle authenticated connections
When the ConnectionFlood test runs for 5 minutes
Then PgBouncer accepts all connections without refusal
And Postgres backend connections stay bounded at ~125
```

---

## 9. Directory Structure

```
nukelab/
├── frontend/                          # Vite + React 19 SPA
│   ├── src/
│   │   ├── routes/                   # TanStack Router file-based routes
│   │   │   ├── __root.tsx            # Root layout
│   │   │   ├── index.tsx             # Dashboard home
│   │   │   ├── login.tsx             # Auth page
│   │   │   ├── servers/
│   │   │   │   ├── index.tsx         # Server list
│   │   │   │   └── $serverId/
│   │   │   │       ├── index.tsx     # Server detail
│   │   │   │       └── metrics.tsx   # Server metrics
│   │   │   ├── environments/
│   │   │   ├── users/
│   │   │   ├── admin/
│   │   │   ├── monitoring/
│   │   │   ├── credits/
│   │   │   ├── audit/
│   │   │   └── settings/
│   │   ├── components/               # React components
│   │   │   ├── ui/                   # shadcn/ui primitives
│   │   │   ├── actions/              # Semantic action buttons
│   │   │   ├── data/                 # Data display (tables, cards)
│   │   │   ├── layout/               # Layout components
│   │   │   ├── feedback/             # Toasts, alerts, skeletons
│   │   │   ├── charts/               # Recharts wrappers
│   │   │   └── animations/           # Reusable animation components
│   │   ├── hooks/                    # Custom React hooks
│   │   ├── lib/                      # Utilities, API client
│   │   ├── stores/                   # Zustand stores
│   │   ├── types/                    # TypeScript types
│   │   └── styles/                   # Global styles, themes
│   ├── public/                       # Static assets
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
│
├── backend/                          # FastAPI Application
│   ├── app/                         # Main application
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── config.py                # Configuration
│   │   ├── dependencies.py          # FastAPI dependencies
│   │   ├── middleware/              # Custom middleware
│   │   │   ├── request_metrics.py   # HTTP request metrics middleware
│   │   │   └── ... (audit, rate limit, etc.)
│   ├── api/                         # API routes
│   │   ├── __init__.py
│   │   ├── auth.py                  # Auth endpoints
│   │   ├── users.py                 # User endpoints
│   │   ├── servers.py               # Server endpoints
│   │   ├── environments.py          # Environment endpoints
│   │   ├── plans.py                 # Plan endpoints
│   │   ├── monitoring.py            # Monitoring endpoints
│   │   ├── audit.py                 # Audit endpoints
│   │   ├── preferences.py           # User preferences endpoints
│   │   └── system.py                # System endpoints
│   ├── core/                        # Core modules
│   │   ├── __init__.py
│   │   ├── security.py              # JWT, bcrypt, permissions
│   │   ├── roles.py                 # Role-permission matrix with precomputed O(1) expansion cache
│   │   ├── cache.py                 # Redis caching: msgpack, circuit breaker, stampede protection, SET invalidation
│   │   ├── redis_client.py          # Shared async Redis client singleton
│   │   ├── exceptions.py            # Custom exceptions
│   │   ├── logging.py               # Structured logging (JSON/text formatters)
│   │   └── context.py               # contextvars (correlation_id)
│   ├── services/                    # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py          # Auth business logic
│   │   ├── user_service.py          # User business logic
│   │   ├── server_service.py        # Server/container management
│   │   ├── environment_service.py   # Environment management
│   │   ├── plan_service.py          # Plan management
│   │   ├── monitoring_service.py    # Metrics collection
│   │   ├── audit_service.py         # Audit logging
│   │   ├── credit_service.py        # Credit management
│   │   ├── preferences_service.py   # User preferences
│   │   └── notification_service.py  # Notifications
│   ├── models/                      # SQLAlchemy & Pydantic models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── server.py
│   │   ├── environment.py
│   │   ├── plan.py
│   │   ├── credit.py
│   │   ├── preferences.py
│   │   ├── audit.py
│   │   └── request_metric.py        # HTTP request telemetry
│   ├── db/                          # Database
│   │   ├── __init__.py
│   │   ├── base.py                  # SQLAlchemy base
│   │   ├── session.py               # Async session
│   │   └── repositories/            # Repository pattern
│   ├── docker/                      # Docker integration
│   │   ├── __init__.py
│   │   ├── client.py                # Async Docker client
│   │   ├── spawner.py               # Container spawning logic
│   │   └── monitoring.py            # Container metrics
│   ├── websocket/                   # WebSocket handlers
│   │   ├── __init__.py
│   │   ├── manager.py               # Connection manager
│   │   └── handlers.py              # Event handlers
│   ├── workers/                     # Celery tasks
│   │   ├── __init__.py
│   │   ├── cleanup.py               # Cleanup tasks
│   │   ├── notifications.py         # Notification tasks
│   │   └── reports.py               # Report generation
│   ├── tests/                       # Test suite
│   │   ├── unit/
│   │   ├── integration/
│   │   └── e2e/
│   ├── alembic/                     # Database migrations
│   ├── requirements.txt             # Python dependencies
│   ├── Dockerfile                   # Backend container
│   └── pyproject.toml               # Project metadata
│
├── database/                         # Database Files
│   ├── schema.sql                   # Full schema
│   ├── migrations/                  # Alembic migrations
│   └── seeds/                       # Seed data
│
├── environments/                     # Example Environment Dockerfiles (admin-created)
│   ├── base/                        # Base image template
│   │   └── Dockerfile
│   └── dev/                         # Development environment template
│       ├── Dockerfile
│       ├── nginx.conf
│       └── startup.sh
│
├── infrastructure/                   # Infrastructure Configuration
│   ├── traefik/                     # Traefik Configuration
│   │   └── traefik.yml              # Static configuration
│   └── dynamic/                     # Dynamic configuration
│       ├── middlewares.yml
│       └── routers.yml
│
├── monitoring/                       # Monitoring Stack
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── grafana/
│   │   └── dashboards/
│   └── alertmanager/
│       └── config.yml
│
├── scripts/                          # Utility Scripts
│   ├── setup.sh                     # Initial setup
│   ├── migrate.sh                   # Database migrations
│   ├── build-environments.sh        # Build all environments
│   └── backup.sh                    # Backup script
│
├── compose.yml                      # Development stack
├── docker-compose.prod.yml          # Production stack

├── README.md                        # Project documentation
└── .env.example                     # Environment template
```

---

## 10. Infrastructure & Deployment

### 10.1 Docker Compose (Development)

```yaml
version: "3.8"

services:
  # Reverse Proxy
  traefik:
    image: traefik:v3.0
    command:
      - --api.insecure=true
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.letsencrypt.acme.tlschallenge=true
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - nukelab

  # Frontend
  frontend:
    build: ./frontend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.frontend.rule=PathPrefix(`/app`)"
      - "traefik.http.services.frontend.loadbalancer.server.port=80"
    networks:
      - nukelab

  # Backend API
  backend:
    build: ./backend
    environment:
      - DATABASE_USER=nukelab
      - DATABASE_PASSWORD=password
      - DATABASE_NAME=nukelab
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - REDIS_URL=redis://redis:6379/0
      - AUTH_MODE=local
      - JWT_SECRET=${JWT_SECRET}
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.backend.rule=PathPrefix(`/api`)"
      - "traefik.http.services.backend.loadbalancer.server.port=8000"
    depends_on:
      - postgres
      - redis
    networks:
      - nukelab

  # Database
  postgres:
    image: postgres:18
    environment:
      - POSTGRES_USER=nukelab
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=nukelab
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - nukelab

  # Cache/Queue
  redis:
    image: redis:7-alpine
    networks:
      - nukelab

  # Background Workers
  celery:
    build: ./backend
    command: celery -A app.workers worker --loglevel=info
    environment:
      - DATABASE_USER=nukelab
      - DATABASE_PASSWORD=password
      - DATABASE_NAME=nukelab
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - postgres
    networks:
      - nukelab

  # Scheduler
  celery-beat:
    build: ./backend
    command: celery -A app.workers beat --loglevel=info
    environment:
      - DATABASE_USER=nukelab
      - DATABASE_PASSWORD=password
      - DATABASE_NAME=nukelab
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - postgres
    networks:
      - nukelab

volumes:
  postgres-data:

networks:
  nukelab:
    name: nukelab-network
```

### 10.2 Production Deployment

**Single Server (Docker Compose)**
- Use `docker-compose.prod.yml`
- Enable TLS via Let's Encrypt
- Resource limits on all containers
- Log rotation
- Automated backups

**Kubernetes (Future)**
- Helm chart for easy deployment
- Horizontal Pod Autoscaler for API
- Persistent Volume Claims for user data
- Network Policies for security
- Pod Security Standards
- Ingress with Traefik

---

## 11. Security Considerations

### 11.1 Authentication & Authorization

- JWT tokens with short expiry (15 minutes)
- Refresh tokens with rotation
- HttpOnly cookies for web clients
- Authorization headers for API clients
- bcrypt with 12+ rounds for local auth

### 11.2 Container Security

- Run containers as non-root
- Read-only root filesystems
- Drop all capabilities
- Resource limits enforced
- Network isolation
- No privileged containers

### 11.3 Network Security

- TLS 1.3 everywhere
- WebSocket over WSS
- Rate limiting on all endpoints
- IP allowlist for admin endpoints
- CORS properly configured

### 11.4 Data Security

- Encrypt data at rest (volumes)
- Encrypt data in transit (TLS)
- No secrets in code or images
- Secret rotation
- Regular security audits

---

## 12. Monitoring & Observability

### 12.1 Metrics

| Metric | Source | Storage |
|--------|--------|---------|
| Container CPU/Memory/Disk | Docker Stats API | PostgreSQL + Prometheus |
| API Request Latency | FastAPI Middleware | Prometheus |
| Error Rate | Structured Logs | Prometheus |
| Active Users | Application | Prometheus |
| Server Lifecycle Events | Application | PostgreSQL |

### 12.2 Logging

- Structured JSON logging
- Correlation IDs for request tracing
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Centralized logging (Loki or ELK stack)

### 12.3 Alerting

- High resource usage
- Container crashes
- API errors
- Security events
- Backup failures

---

## 13. Future Enhancements

### 13.1 Collaboration Features

- Shared sessions (multiple users viewing same NukeIDE)
- Real-time cursor tracking
- Comments and annotations
- Version control integration

### 13.2 AI Integration

- AI assistant panel in NukeIDE
- Code generation for OpenMC/Geant4
- Error analysis and suggestions
- Automated simulation optimization

### 13.3 Marketplace

- Simulation templates
- Community environments
- Plugin system for NukeIDE
- Template sharing

### 13.4 Enterprise Features

- SAML/LDAP/AD integration
- Organization isolation
- Billing and usage tracking
- SLA monitoring
- Compliance reporting

---

## 14. Development Guidelines

### 14.1 Code Style

- **Python**: Black formatter, isort, flake8, mypy
- **TypeScript**: Prettier, ESLint, strict mode
- **Commits**: Conventional commits (`feat:`, `fix:`, `docs:`, etc.)

### 14.2 Testing Requirements

- Unit tests: >80% coverage
- Integration tests: All API endpoints
- E2E tests: Critical user flows
- Load tests: 100+ concurrent users

### 14.3 Documentation

- API documentation: Auto-generated OpenAPI/Swagger
- Code documentation: Docstrings and TypeScript types
- User documentation: Markdown guides
- Deployment documentation: Step-by-step guides

---

## 15. Appendix

### 15.1 Environment Variables

```env
# Application
APP_NAME=NukeLab
APP_ENV=development  # development, staging, production
APP_DEBUG=true
APP_URL=https://nukelab.org

# Database
DATABASE_USER=user
DATABASE_PASSWORD=pass
DATABASE_NAME=db
DATABASE_HOST=host
DATABASE_PORT=5432
# Optional override; when empty the backend builds DATABASE_URL from the components above
# DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
DATABASE_POOL_SIZE=20

# Redis
REDIS_URL=redis://localhost:6379/0

# Auth
AUTH_MODE=local  # local, nukehub
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=15
JWT_REFRESH_EXPIRE_DAYS=7

# NukeHub Auth (production)
OAUTH_URL=https://auth.nukehub.org
OAUTH_REALM=nukehub
OAUTH_CLIENT_ID=nukelab-platform
OAUTH_CLIENT_SECRET=xxx

# Docker
DOCKER_SOCKET=/var/run/docker.sock
DOCKER_NETWORK=nukelab-network
DOCKER_REGISTRY=registry.nukelab.org

# Traefik
TRAEFIK_ENTRYPOINT=web
TRAEFIK_CERT_RESOLVER=letsencrypt

# Monitoring
PROMETHEUS_ENABLED=true
GRAFANA_ENABLED=true
SENTRY_DSN=xxx

# Notifications
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=xxx
SMTP_PASSWORD=xxx
SLACK_WEBHOOK_URL=xxx

# Resource Limits
DEFAULT_MAX_CPU=4
DEFAULT_MAX_MEMORY=8Gi
DEFAULT_MAX_DISK=50Gi
DEFAULT_MAX_SERVERS=3
```

### 15.2 Glossary

| Term | Definition |
|------|------------|
| **NukeIDE** | Eclipse Theia-based IDE for nuclear engineering |
| **Environment** | Pre-configured Docker image with specific tools |
| **Server** | Running container instance for a user |
| **RBAC** | Role-Based Access Control |
| **Traefik** | Cloud-native reverse proxy and load balancer |
| **NukeHub Auth** | OAuth2 identity and access management provider |

---

## 16. Decision Log

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-04-27 | FastAPI over Django | Better async/WS performance | Approved |
| 2026-04-27 | Next.js 16 over 14 | Turbopack stable, Cache Components, React Compiler | **Revised** |
| 2026-04-29 | Vite + React 19 SPA over Next.js | Zero Node.js runtime, RAM savings, TanStack ecosystem | Approved |
| 2026-04-27 | Traefik v3 over Nginx | Dynamic routing, K8s ready | Approved |
| 2026-04-27 | PostgreSQL 18 | Latest stable, JSONB performance | Approved |
| 2026-04-27 | Nginx auth agent in containers | Self-contained auth, fast | Approved |
| 2026-04-27 | Local auth for dev | Easy testing without NukeHub Auth | Approved |
| 2026-04-27 | Separate dev environment | Fast builds for testing | Approved |
| 2026-04-27 | Server Plans separate from Environments | Flexible resource allocation per environment | Approved |
| 2026-04-27 | NUKE currency system | Fair resource allocation on limited hardware (38 CPU, 76GB) | Approved |
| 2026-04-27 | Queue-based scheduling | Handle resource scarcity gracefully | Approved |
| 2026-04-27 | Daily NUKE allowance with no rollover | Prevent hoarding, encourage fair use | Approved |
| 2026-04-27 | User Preferences/Defaults | Save default environment/plan/settings per user | Approved |
| 2026-05-15 | JWT-only for bulk/sensitive admin ops | API tokens scoped for automation; bulk actions are high-impact and require session auth | Approved |
| 2026-05-15 | `Alt+N` over `Ctrl+N` for quick spawn | Avoids Firefox "New Window" conflict and other OS shortcut collisions | Approved |
| 2026-05-20 | Extracted spawner helpers for bulk ops | Reuse existing start/stop/restart/delete logic instead of duplicating container orchestration code | Approved |
| 2026-05-24 | DataTable row selection for bulk actions | Consistent UX pattern across servers, workspaces, and volumes tables | Approved |

---

**Next Steps**: Phases 1–5, 7, and 8 are complete. Platform is production-hardened with PgBouncer, load testing infrastructure, structured logging, metrics, graceful shutdown, rate limiting, CSRF, security headers, IP restrictions, request size limits, database connection pooling, Redis response caching, Prometheus + Grafana, Sentry, database profiling tooling, OWASP Top 10 audit, and dependency scanning. Recommended next work:

1. **Environment image build pipeline** — automated builds, registry integration, image versioning, and base-image updates
2. **CDN for static assets** — quick production performance win for the Vite SPA
3. **Blue-green deployment** — extend CI/CD with a zero-downtime deploy strategy to a live server
4. **Secret management** — HashiCorp Vault or Sealed Secrets integration
5. **Penetration testing** — third-party penetration test before public production launch
6. **Phase 6 Kubernetes items** remain future goals for multi-node scaling — only pursue after you've saturated a single large server (32+ cores, 128GB+ RAM) and proven you need distribution
