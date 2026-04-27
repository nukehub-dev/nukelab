# NukeLab Platform v2.0 — Architecture & Implementation Plan

**Status**: Draft v1.0  
**Last Updated**: April 27, 2026  
**Target Timeline**: 6+ months  
**Tech Stack**: Next.js 16, FastAPI, PostgreSQL 18, Redis, Traefik v3, Docker/Podman

---

## 1. Executive Summary

NukeLab v2.0 is a ground-up rebuild of the multi-user scientific computing platform, replacing JupyterHub with a custom industrial-grade orchestration layer. The platform provides granular RBAC, real-time resource monitoring, multi-environment support, and a modern Next.js management interface.

**Key Improvements over v1.0:**
- Granular role-based access control (6+ roles, 20+ permissions)
- Real-time per-container resource monitoring (CPU, memory, disk, GPU)
- Multiple environment templates (neutronics, multiphysics, visualization, base)
- Modern Next.js admin dashboard with live metrics
- Audit logging for compliance
- WebSocket-native architecture
- Kubernetes migration path

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Traefik v3 (Reverse Proxy)                   │
│                                                                  │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐   │
│  │ /app/*     │  │ /api/*     │  │ /user/{username}/*       │   │
│  │ → Next.js  │  │ → FastAPI  │  │ → NukeIDE Container      │   │
│  │   Frontend │  │   Backend  │  │   (Nginx + Theia)        │   │
│  └────────────┘  └────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Next.js 16  │    │  FastAPI Backend │    │  PostgreSQL  │
│  App Router  │◄──►│  + WebSocket     │    │  18 + Redis  │
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
| **Frontend** | Next.js 16 (App Router) | Admin dashboard, user portal, real-time monitoring UI |
| **Backend API** | FastAPI | Auth, user/server management, Docker orchestration, metrics collection |
| **Database** | PostgreSQL 18 | Users, roles, permissions, environments, servers, audit logs, metrics history |
| **Cache/Queue** | Redis | Sessions, pub/sub, Celery broker, real-time message bus |
| **Background Workers** | Celery | Server cleanup, notifications, report generation, scheduled tasks |
| **User Environments** | NukeIDE + Nginx | Theia IDE with built-in JWT validation proxy |

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

### 3.2 Why Next.js 16 App Router?

| Factor | Next.js 16 App Router | React SPA (Vite) |
|--------|----------------------|------------------|
| **SSR/SSG** | Built-in Server Components | Client-side only |
| **API Routes** | Built-in (can proxy to FastAPI) | Requires separate backend |
| **Real-time** | Server-Sent Events + WebSocket support | WebSocket only |
| **Performance** | Turbopack stable, 2-5x faster builds | Full bundle download |
| **Caching** | Cache Components, explicit caching control | Manual caching |
| **React Compiler** | Automatic memoization, fewer re-renders | Manual optimization |
| **SEO** | Excellent | Poor |

**Decision**: Next.js 16 App Router provides:
- **Turbopack** (stable): 2-5x faster production builds, up to 10x faster Fast Refresh
- **Cache Components**: Explicit, opt-in caching model with Partial Prerendering (PPR)
- **React Compiler** (stable): Automatic memoization with zero manual code changes
- **Enhanced Routing**: Layout deduplication, incremental prefetching, faster navigation
- **React 19.2**: View Transitions, Activity API, improved concurrent features

This makes Next.js 16 significantly faster and more efficient for our real-time dashboard requirements.

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

#### Predefined Environments

| Environment | Description | Tools Included |
|-------------|-------------|----------------|
| `neutronics` | Monte Carlo neutron transport | OpenMC, DAGMC, NJOY, PyNE, cross-sections |
| `multiphysics` | Multi-physics simulations | MOAB, LibMesh, OpenMC, additional physics codes |
| `visualization` | Post-processing and visualization | ParaView, Trame, Python plotting libraries |
| `base` | Minimal environment | Python 3.12, basic scientific Python stack |

#### Environment Properties

```yaml
name: "neutronics"
description: "Monte Carlo neutron transport environment"
image: "nukelab/environments:neutronics-v1.0"
default_resources:
  cpu: 4
  memory: "8Gi"
  disk: "50Gi"
  gpu: 0
max_resources:
  cpu: 16
  memory: "64Gi"
  disk: "500Gi"
  gpu: 1
startup_script: "/opt/nukelab/startup.sh"
branding:
  color: "#2563eb"
  icon: "atom"
```

### 4.3 Real-Time Resource Monitoring

#### Metrics Collected

- **CPU**: Usage percentage, throttling events
- **Memory**: Used, available, cache, swap
- **Disk**: I/O throughput, space usage
- **Network**: RX/TX bytes, packets, errors
- **GPU**: Utilization, memory, temperature (if available)
- **Processes**: Count, zombie processes

#### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Docker Stats   │────►│  FastAPI WS     │────►│  Next.js        │
│  API (async)    │     │  Endpoint       │     │  Dashboard      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         ▼                                               ▼
┌─────────────────┐                            ┌─────────────────┐
│  PostgreSQL     │                            │  Recharts/D3.js │
│  (time-series)  │                            │  Visualization  │
└─────────────────┘                            └─────────────────┘
```

#### Features

- Live dashboard updates every 1-2 seconds via WebSocket
- Historical data retention (configurable: 7d, 30d, 90d)
- Per-user and global views
- Resource quota alerts (email, Slack, webhook)
- Top consumers leaderboard
- Export to CSV/PDF

### 4.4 Audit & Compliance

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

#### Production: Keycloak (NukeHub)

```
User Browser
    │
    ▼
Next.js Frontend
    │
    ▼
Keycloak Login (auth.nukehub.org)
    │
    ▼
JWT Token (signed by Keycloak)
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
Next.js Login Form
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
# Auth mode: "keycloak" | "local"
AUTH_MODE=local

# Keycloak settings (production)
KEYCLOAK_URL=https://auth.nukehub.org
KEYCLOAK_REALM=nukehub
KEYCLOAK_CLIENT_ID=nukelab-platform
KEYCLOAK_CLIENT_SECRET=xxx

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
    
    # Status
    is_active: bool
    is_verified: bool
    last_login: datetime
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
    
    # Docker
    container_id: str
    image: str
    status: ServerStatus  # pending, starting, running, stopping, stopped, error
    
    # Resources
    allocated_cpu: int
    allocated_memory: str
    allocated_disk: str
    allocated_gpu: int
    
    # Networking
    internal_port: int  # Theia port (3000)
    external_url: str   # /user/{username}/{server_id}
    
    # Timestamps
    started_at: datetime
    stopped_at: datetime
    last_activity: datetime
    created_at: datetime
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
POST   /api/auth/keycloak/callback  # Keycloak OAuth callback
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

- [ ] **Project Structure**
  - [ ] Initialize monorepo structure
  - [ ] `frontend/` — Next.js 16 with TypeScript, Tailwind, shadcn/ui
  - [ ] `backend/` — FastAPI with asyncpg, Pydantic, Docker SDK
  - [ ] `database/` — PostgreSQL 18 schema and migrations
  - [ ] `environments/` — Environment Dockerfiles
  - [ ] `docker-compose.yml` — Full stack orchestration
  - [ ] `traefik/` — Traefik configuration

- [ ] **Database Setup**
  - [ ] Create PostgreSQL 18 schema (users, roles, permissions, servers, environments, audit_logs)
  - [ ] Set up migration system (Alembic)
  - [ ] Seed default roles and super_admin user
  - [ ] Create indexes for common queries

- [ ] **Redis Setup**
  - [ ] Configure Redis for sessions
  - [ ] Configure Redis for pub/sub
  - [ ] Configure Redis for Celery broker

- [ ] **Authentication System**
  - [ ] Local auth: bcrypt password hashing, JWT generation
  - [ ] Keycloak auth: OAuth2 flow, JWT validation
  - [ ] Auth middleware for FastAPI
  - [ ] Permission checking decorators
  - [ ] Role-based route guards

- [ ] **NukeIDE Containerization**
  - [ ] Create `environments/dev/Dockerfile`
    - [ ] Base: Debian 13 or Ubuntu 24.04
    - [ ] Install Node.js 22
    - [ ] Build NukeIDE (clone from nuke-ide repo)
    - [ ] Install nginx
    - [ ] Add nginx auth proxy config
    - [ ] Add startup script
  - [ ] Update `environments/default/Dockerfile`
    - [ ] Same structure as dev but with nuclear tools
    - [ ] Keep existing tool installations
    - [ ] Add nginx auth proxy

- [ ] **Container Spawning**
  - [ ] Docker SDK integration (async)
  - [ ] Server spawn endpoint (`POST /api/servers`)
  - [ ] Container lifecycle management (start, stop, delete)
  - [ ] Traefik dynamic routing labels
  - [ ] Volume creation and mounting

- [ ] **Basic Frontend**
  - [ ] Login page (local auth mode)
  - [ ] Dashboard shell with sidebar navigation
  - [ ] User profile page
  - [ ] Server list page (basic)
  - [ ] Server spawn form (environment selection)

- [ ] **Traefik Configuration**
  - [ ] Dynamic Docker provider
  - [ ] Route: `/app/*` → Next.js
  - [ ] Route: `/api/*` → FastAPI
  - [ ] Route: `/user/{username}` → user containers
  - [ ] WebSocket upgrade handling
  - [ ] Basic rate limiting

#### Deliverables

- [ ] Admin can log in via local auth
- [ ] Admin can spawn a NukeIDE container
- [ ] Admin can access NukeIDE via browser
- [ ] Basic dashboard UI functional
- [ ] All services running via docker-compose

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

- [ ] **RBAC Implementation**
  - [ ] Role model with permission matrix
  - [ ] Permission checking middleware
  - [ ] Route-level permission decorators
  - [ ] Frontend permission hooks/components

- [ ] **User CRUD**
  - [ ] Create user (admin/moderator)
  - [ ] Read user list with filters (role, status, search)
  - [ ] Update user (profile, role, quotas)
  - [ ] Delete/disable user
  - [ ] Bulk operations

- [ ] **User Profile**
  - [ ] View own profile
  - [ ] Edit own profile
  - [ ] Change password
  - [ ] View own servers and usage

- [ ] **Admin Dashboard**
  - [ ] User management table
  - [ ] Role assignment UI
  - [ ] Permission matrix editor
  - [ ] User activity timeline
  - [ ] Server management table
  - [ ] Bulk actions (start all, stop all, delete all)

- [ ] **Server Lifecycle**
  - [ ] Start/stop/restart/delete servers
  - [ ] Server status polling
  - [ ] Server logs viewer
  - [ ] Server detail page

#### Deliverables

- [ ] Admin can create users with specific roles
- [ ] Permission system prevents unauthorized actions
- [ ] Admin dashboard shows all users and servers
- [ ] Users can manage own profile and servers

#### Success Criteria

```gherkin
Given I am an admin
When I create a new user with role "moderator"
Then the user can log in
And the user can create other users
But the user cannot access other users' servers

Given I am a regular user
When I try to access admin dashboard
Then I get a 403 Forbidden error
```

---

### Phase 3: Environment Templates & Resource Management (Weeks 7-9)

**Goal**: Multiple environments, resource quotas, and limits

#### Tasks

- [ ] **Environment Template System**
  - [ ] Environment CRUD API
  - [ ] Environment builder UI (admin)
  - [ ] Environment selection in spawn form
  - [ ] Environment-specific branding
  - [ ] Environment activation/deactivation

- [ ] **Resource Quotas**
  - [ ] Quota model (per-user, per-role)
  - [ ] Quota enforcement on spawn
  - [ ] Quota usage tracking
  - [ ] Quota exceeded alerts

- [ ] **Resource Limits**
  - [ ] Docker container limits (CPU, memory)
  - [ ] Disk quota enforcement
  - [ ] GPU allocation (if available)
  - [ ] Limit overrides for admins

- [ ] **Volume Management**
  - [ ] Persistent user volumes
  - [ ] Shared workspace volumes
  - [ ] Volume backup/restore
  - [ ] Volume quota enforcement

- [ ] **Environment Images**
  - [ ] Build system for environment images
  - [ ] Image registry integration
  - [ ] Image versioning
  - [ ] Base image updates

#### Deliverables

- [ ] Multiple environments available (dev, neutronics, multiphysics, visualization, base)
  - [ ] Users can choose environment when spawning
  - [ ] Resource quotas enforced
  - [ ] Admin can create/modify environments

#### Success Criteria

```gherkin
Given I am a user
When I spawn a server with "neutronics" environment
Then the container has OpenMC and DAGMC installed
And the container has 4 CPU and 8GB RAM allocated

Given I have reached my server limit (max_servers=3)
When I try to spawn a 4th server
Then I get an error: "Server limit reached"
```

---

### Phase 4: Real-Time Monitoring Dashboard (Weeks 10-12)

**Goal**: Live resource monitoring, historical data, and alerting

#### Tasks

- [ ] **Metrics Collection**
  - [ ] Docker Stats API integration (async streaming)
  - [ ] Custom metrics collector (CPU, memory, disk, network)
  - [ ] GPU metrics (nvidia-smi integration)
  - [ ] Metrics storage in PostgreSQL (time-series)

- [ ] **WebSocket Streaming**
  - [ ] WebSocket endpoint for real-time metrics
  - [ ] Subscription model (subscribe to specific servers/users)
  - [ ] Efficient data serialization (MessagePack or JSON)
  - [ ] Connection management and cleanup

- [ ] **Monitoring Dashboard**
  - [ ] Global resource overview (all users/servers)
  - [ ] Per-user resource usage page
  - [ ] Per-server real-time charts
  - [ ] Top consumers leaderboard
  - [ ] Resource usage trends (7d, 30d, 90d)

- [ ] **Alerting System**
  - [ ] Alert rules (quota thresholds, container crashes)
  - [ ] Email notifications (SMTP integration)
  - [ ] Slack/Discord webhooks
  - [ ] In-app notifications
  - [ ] Alert history and acknowledgment

- [ ] **Health Checks**
  - [ ] Container health checks
  - [ ] Auto-restart on failure
  - [ ] Unhealthy server notifications
  - [ ] System health dashboard

#### Deliverables

- [ ] Real-time monitoring dashboard with live charts
  - [ ] Admin can see all users' resource usage
  - [ ] Users can see own usage
  - [ ] Alerts sent when quotas exceeded

#### Success Criteria

```gherkin
Given a server is running
When I open the monitoring dashboard
Then I see CPU and memory usage updating every second

Given a user exceeds their memory quota
When the threshold is crossed
Then the admin receives a Slack notification
And the user receives an in-app warning
```

---

### Phase 5: Advanced Platform Features (Weeks 13-16)

**Goal**: Industrial-grade features for production use

#### Tasks

- [ ] **Audit Logging**
  - [ ] Audit middleware (auto-log all admin actions)
  - [ ] Audit log viewer with filters
  - [ ] Audit log export (CSV, PDF, JSON)
  - [ ] Tamper-evident storage

- [ ] **Server Scheduling**
  - [ ] Cron-based server scheduling
  - [ ] Recurring schedules (daily, weekly)
  - [ ] Schedule management UI
  - [ ] Timezone support

- [ ] **API Keys**
  - [ ] Scoped API key generation
  - [ ] API key management UI
  - [ ] API key usage tracking
  - [ ] Revocation and expiration

- [ ] **Shared Workspaces**
  - [ ] Shared volume creation
  - [ ] Permission management (read-only, read-write)
  - [ ] Shared workspace UI
  - [ ] Collaboration features

- [ ] **Notifications**
  - [ ] Webhook configuration
  - [ ] Slack/Discord integration
  - [ ] Email templates
  - [ ] In-app notification center

- [ ] **Maintenance Mode**
  - [ ] Graceful user draining
  - [ ] Maintenance page
  - [ ] Scheduled maintenance windows
  - [ ] User notifications

- [ ] **Rate Limiting & Security**
  - [ ] Traefik rate limiting middleware
  - [ ] API rate limiting
  - [ ] DDoS protection
  - [ ] IP allowlist/blocklist

- [ ] **Backup & Restore**
  - [ ] Automated volume backups
  - [ ] Backup scheduling
  - [ ] Point-in-time restore
  - [ ] Cross-region backup (future)

#### Deliverables

- [ ] Complete audit trail for all actions
  - [ ] Server scheduling system
  - [ ] API key management
  - [ ] Shared workspaces
  - [ ] Advanced notifications

#### Success Criteria

```gherkin
Given I am an admin
When I delete a user
Then the action is logged in the audit trail
And I can see the before/after state

Given I schedule a server to start at 9 AM daily
When 9 AM arrives
Then the server starts automatically
```

---

### Phase 6: Production Hardening & Kubernetes (Weeks 17-20)

**Goal**: Production readiness and Kubernetes migration

#### Tasks

- [ ] **Testing**
  - [ ] Unit tests (backend >80% coverage)
  - [ ] Integration tests (API endpoints)
  - [ ] E2E tests (Playwright)
  - [ ] Load testing (Locust/k6)

- [ ] **Security**
  - [ ] OWASP Top 10 audit
  - [ ] Dependency scanning (Snyk, Dependabot)
  - [ ] Secret management (HashiCorp Vault or Sealed Secrets)
  - [ ] Security headers (HSTS, CSP, X-Frame-Options)
  - [ ] Penetration testing

- [ ] **Performance**
  - [ ] Database query optimization
  - [ ] Caching strategy (Redis)
  - [ ] CDN for static assets
  - [ ] Connection pooling

- [ ] **Observability**
  - [ ] Prometheus metrics export
  - [ ] Grafana dashboards
  - [ ] Structured logging (JSON)
  - [ ] Distributed tracing (OpenTelemetry)
  - [ ] Error tracking (Sentry)

- [ ] **Kubernetes**
  - [ ] Kubernetes manifests (Deployments, Services, Ingress)
  - [ ] Helm chart
  - [ ] Horizontal Pod Autoscaler
  - [ ] Persistent Volume Claims
  - [ ] ConfigMaps and Secrets
  - [ ] Network Policies
  - [ ] Pod Security Standards

- [ ] **Deployment**
  - [ ] CI/CD pipeline (GitHub Actions)
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

## 9. Directory Structure

```
nukelab/
├── frontend/                          # Next.js 16 Application
│   ├── app/                          # App Router
│   │   ├── (auth)/                   # Auth routes (login, register)
│   │   ├── (dashboard)/              # Dashboard routes
│   │   │   ├── admin/               # Admin pages
│   │   │   │   ├── users/           # User management
│   │   │   │   ├── servers/         # Server management
│   │   │   │   ├── environments/    # Environment templates
│   │   │   │   ├── monitoring/      # Real-time monitoring
│   │   │   │   ├── audit/           # Audit logs
│   │   │   │   └── settings/        # Platform settings
│   │   │   ├── user/                # User pages
│   │   │   │   ├── profile/         # User profile
│   │   │   │   ├── servers/         # My servers
│   │   │   │   └── usage/           # My resource usage
│   │   │   └── page.tsx             # Dashboard home
│   │   ├── api/                     # Next.js API routes (auth proxy)
│   │   └── layout.tsx               # Root layout
│   ├── components/                  # React components
│   │   ├── ui/                      # shadcn/ui components
│   │   ├── layout/                  # Layout components
│   │   ├── monitoring/              # Monitoring charts
│   │   └── forms/                   # Form components
│   ├── hooks/                       # Custom React hooks
│   ├── lib/                         # Utilities
│   ├── types/                       # TypeScript types
│   └── public/                      # Static assets
│
├── backend/                          # FastAPI Application
│   ├── app/                         # Main application
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── config.py                # Configuration
│   │   ├── dependencies.py          # FastAPI dependencies
│   │   └── middleware/              # Custom middleware
│   ├── api/                         # API routes
│   │   ├── __init__.py
│   │   ├── auth.py                  # Auth endpoints
│   │   ├── users.py                 # User endpoints
│   │   ├── servers.py               # Server endpoints
│   │   ├── environments.py          # Environment endpoints
│   │   ├── monitoring.py            # Monitoring endpoints
│   │   ├── audit.py                 # Audit endpoints
│   │   └── system.py                # System endpoints
│   ├── core/                        # Core modules
│   │   ├── __init__.py
│   │   ├── security.py              # JWT, bcrypt, permissions
│   │   ├── exceptions.py            # Custom exceptions
│   │   └── logging.py               # Structured logging
│   ├── services/                    # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py          # Auth business logic
│   │   ├── user_service.py          # User business logic
│   │   ├── server_service.py        # Server/container management
│   │   ├── environment_service.py   # Environment management
│   │   ├── monitoring_service.py    # Metrics collection
│   │   ├── audit_service.py         # Audit logging
│   │   └── notification_service.py  # Notifications
│   ├── models/                      # Pydantic models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── server.py
│   │   ├── environment.py
│   │   └── audit.py
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
├── environments/                     # Environment Images
│   ├── base/                        # Base image (shared layers)
│   │   └── Dockerfile
│   ├── dev/                         # Development environment
│   │   ├── Dockerfile
│   │   ├── nginx.conf               # Nginx auth proxy config
│   │   └── startup.sh               # Container startup script
│   ├── neutronics/                  # Neutronics environment
│   │   ├── Dockerfile
│   │   ├── nginx.conf
│   │   └── startup.sh
│   ├── multiphysics/                # Multiphysics environment
│   │   ├── Dockerfile
│   │   ├── nginx.conf
│   │   └── startup.sh
│   └── visualization/               # Visualization environment
│       ├── Dockerfile
│       ├── nginx.conf
│       └── startup.sh
│
├── traefik/                          # Traefik Configuration
│   ├── traefik.yml                  # Static configuration
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
├── docker-compose.yml               # Development stack
├── docker-compose.prod.yml          # Production stack
├── Makefile                         # Common commands
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
      - "traefik.http.services.frontend.loadbalancer.server.port=3000"
    networks:
      - nukelab

  # Backend API
  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://nukelab:password@postgres:5432/nukelab
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
      - DATABASE_URL=postgresql+asyncpg://nukelab:password@postgres:5432/nukelab
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
      - DATABASE_URL=postgresql+asyncpg://nukelab:password@postgres:5432/nukelab
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
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
DATABASE_POOL_SIZE=20

# Redis
REDIS_URL=redis://localhost:6379/0

# Auth
AUTH_MODE=local  # local, keycloak
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=15
JWT_REFRESH_EXPIRE_DAYS=7

# Keycloak (production)
KEYCLOAK_URL=https://auth.nukehub.org
KEYCLOAK_REALM=nukehub
KEYCLOAK_CLIENT_ID=nukelab-platform
KEYCLOAK_CLIENT_SECRET=xxx

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
| **Keycloak** | Open-source identity and access management |

---

## 16. Decision Log

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-04-27 | FastAPI over Django | Better async/WS performance | Approved |
| 2026-04-27 | Next.js 16 over 14 | Turbopack stable, Cache Components, React Compiler | Approved |
| 2026-04-27 | Traefik v3 over Nginx | Dynamic routing, K8s ready | Approved |
| 2026-04-27 | PostgreSQL 18 | Latest stable, JSONB performance | Approved |
| 2026-04-27 | Nginx auth agent in containers | Self-contained auth, fast | Approved |
| 2026-04-27 | Local auth for dev | Easy testing without Keycloak | Approved |
| 2026-04-27 | Separate dev environment | Fast builds for testing | Approved |

---

**Next Steps**: Begin Phase 1 implementation upon approval.
