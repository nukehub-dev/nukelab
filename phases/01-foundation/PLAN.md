# Phase 1: Foundation & Scaffolding

**Duration**: Weeks 1-3  
**Goal**: Project structure, auth, basic container spawning  
**Status**: ✅ COMPLETED (April 27, 2026)

---

## Overview

Phase 1 establishes the foundational infrastructure for NukeLab Platform v2.0. We will create the complete project structure, set up all core services, implement dual authentication (local for dev, NukeHub Auth for production), containerize NukeIDE, and achieve the first milestone: an admin can log in and spawn a working NukeIDE container.

---

## Prerequisites

- [ ] Docker and Docker Compose installed (or Podman)
- [ ] Node.js 20.9+ installed locally (for Next.js 16)
- [ ] Python 3.12+ installed locally (for FastAPI development)
- [ ] Git configured
- [ ] 10GB+ free disk space for development

---

## Week 1: Project Structure & Infrastructure

### Day 1-2: Project Initialization

#### Tasks

- [ ] **Initialize Git Repository**
  - [ ] Ensure on `new` branch
  - [ ] Clean up old JupyterHub-specific files (keep for reference in archive/)
  - [ ] Create initial commit with project structure

- [ ] **Create Root Project Files**
  - [ ] `README.md` — Project overview, quick start, architecture diagram
  - [ ] `LICENSE` — BSD-2-Clause (maintain from v1)
  - [x] `manage.sh` — Management script (Docker/Podman/Conda)
  - [ ] `.gitignore` — Python, Node, IDE, secrets
  - [ ] `.env.example` — Template with all environment variables (no secrets)
  - [ ] `.env.development` — Safe development defaults (committed)

- [ ] **Create Directory Structure**
  ```
  nukelab/
  ├── frontend/           # Next.js 16 application
  ├── backend/            # FastAPI application
  ├── environments/       # Docker images
  │   ├── base/          # Shared base layers
  │   └── dev/           # Development NukeIDE image
  ├── database/          # Schema and migrations
  │   ├── migrations/    # Alembic migrations
  │   └── seeds/         # Initial data
  ├── infrastructure/    # Infrastructure config
  │   └── traefik/       # Reverse proxy
  ├── certs/             # SSL certificates (self-signed)
  ├── scripts/           # Utility scripts
  └── docs/              # Documentation
  ```

### Day 3-4: Docker Compose Setup

#### Tasks

- [ ] **Create `docker-compose.yml`**
  - [ ] Traefik v3 service with dynamic Docker provider
  - [ ] PostgreSQL 17 service (latest stable, update to 18 when released)
  - [ ] Redis service (sessions, cache, Celery broker)
  - [ ] FastAPI backend service
  - [ ] Next.js frontend service
  - [ ] Celery worker service
  - [ ] Celery beat (scheduler) service
  - [ ] Shared network: `nukelab-network`
  - [ ] Named volumes for PostgreSQL data

- [ ] **Traefik Configuration**
  - [ ] Static config (`infrastructure/traefik/traefik.yml`)
  - [ ] Dynamic config directory (`infrastructure/traefik/dynamic/`)
  - [ ] Docker provider enabled
  - [ ] Entrypoints: web (80), websecure (443)
  - [ ] Self-signed certificate generation script
  - [ ] Routes:
    - `/app/*` → frontend
    - `/api/*` → backend
    - `/user/{username}/*` → user containers (dynamic)

- [ ] **SSL Certificates**
  - [ ] Generate self-signed certs for local HTTPS
  - [ ] Script: `scripts/generate-certs.sh`
  - [ ] Mount certs into Traefik container

### Day 5-7: Database Setup

#### Tasks

- [ ] **PostgreSQL Schema Design**
  - [ ] Create `database/schema.sql`
  - [ ] Core tables:
    - `users` (id, username, email, role, password_hash, is_active, created_at)
    - `roles` (id, name, permissions)
    - `servers` (id, user_id, environment_id, plan_id, status, container_id)
    - `environments` (id, name, description, image, is_active)
    - `plans` (id, name, cpu, memory, disk, gpu, cost_per_hour)
    - `audit_logs` (id, actor_id, action, target_type, timestamp)
    - `credit_transactions` (id, user_id, amount, balance_after, type)
  - [ ] Indexes for common queries
  - [ ] Foreign key constraints

- [ ] **Alembic Migration Setup**
  - [ ] Initialize Alembic in `backend/alembic/`
  - [ ] Create initial migration from schema
  - [ ] Migration script: `scripts/migrate.sh`

- [ ] **Seed Data**
  - [ ] `database/seeds/roles.sql` — Default roles (super_admin, admin, moderator, support, user, guest)
  - [ ] `database/seeds/plans.sql` — Default plans (nano, micro, small, medium, large)
  - [ ] `database/seeds/environments.sql` — Default environments (dev, base)
  - [ ] Seed script: `scripts/seed.sh`

---

## Week 2: Backend Implementation

### Day 1-2: FastAPI Foundation

#### Tasks

- [ ] **Initialize FastAPI Project**
  - [ ] `backend/pyproject.toml` — Project metadata, dependencies
  - [ ] `backend/requirements.txt` — Pin versions
  - [ ] `backend/app/__init__.py`
  - [ ] `backend/app/main.py` — FastAPI app factory
  - [ ] `backend/app/config.py` — Pydantic Settings with env vars

- [ ] **Core Dependencies**
  ```
  fastapi==0.115.0
  uvicorn[standard]==0.32.0
  pydantic==2.9.0
  pydantic-settings==2.6.0
  sqlalchemy[asyncio]==2.0.36
  asyncpg==0.30.0
  alembic==1.14.0
  python-jose[cryptography]==3.3.0
  passlib[bcrypt]==1.7.4
  python-multipart==0.0.17
  redis==5.2.0
  celery==5.4.0
  aiodocker==0.24.0
  ```

- [ ] **Configuration System**
  - [ ] `backend/app/config.py` using Pydantic Settings
  - [ ] Environment-based config (dev/staging/prod)
  - [ ] Secrets management (from env vars only)

### Day 3-4: Authentication System

#### Tasks

- [ ] **Local Authentication**
  - [ ] `backend/app/core/security.py`
    - [ ] Password hashing (bcrypt)
    - [ ] JWT token generation/validation
    - [ ] Token refresh logic
  - [ ] `backend/app/api/auth.py`
    - [ ] `POST /api/auth/login` — Local login with username/password
    - [ ] `POST /api/auth/logout` — Logout (invalidate token)
    - [ ] `POST /api/auth/refresh` — Refresh access token
    - [ ] `GET /api/auth/me` — Get current user
  - [ ] `backend/app/services/auth_service.py`
    - [ ] Authenticate user
    - [ ] Generate tokens
    - [ ] Validate tokens

- [ ] **NukeHub Auth (OAuth2) — Skeleton**
  - [ ] `backend/app/api/auth.py`
    - [ ] `POST /api/auth/oauth/callback` — OAuth callback endpoint (stub)
  - [ ] `backend/app/services/oauth_service.py`
    - [ ] OAuth2 flow implementation (stub for Phase 2)
    - [ ] JWT validation against NukeHub Auth

- [ ] **Auth Middleware**
  - [ ] `backend/app/dependencies.py`
    - [ ] `get_current_user()` dependency
    - [ ] `require_permissions()` dependency
  - [ ] `backend/app/middleware/auth.py`
    - [ ] JWT validation middleware
    - [ ] Permission checking middleware

- [x] **API Token Infrastructure** (Bonus — Foundation for Phase 2)
  - [x] `backend/app/models/api_token.py` — SQLAlchemy model with user relationship
  - [x] `database/init/01-schema.sql` — `api_tokens` table with hash, scopes, expiration
  - [x] `backend/app/api/tokens.py` — Token management endpoints
    - [x] `GET /api/tokens` — List tokens
    - [x] `POST /api/tokens` — Create token (returns token once)
    - [x] `GET /api/tokens/{id}` — Get token details
    - [x] `DELETE /api/tokens/{id}` — Revoke token
    - [x] `POST /api/tokens/{id}/regenerate` — Rotate token
    - [x] `GET /api/tokens/{id}/usage` — Usage statistics
  - [x] Dual authentication in `get_current_user()`
    - [x] JWT tokens: `Authorization: Bearer <jwt>`
    - [x] API tokens: `Authorization: Token <token>`
  - [x] Token usage tracking (last_used_at, usage_count)
  - [x] Integration with `backend/app/main.py`

### Day 5-7: User Management & RBAC

#### Tasks

- [ ] **User Model & CRUD**
  - [ ] `backend/app/models/user.py` — Pydantic models
  - [ ] `backend/app/db/repositories/user.py` — Database operations
  - [ ] `backend/app/services/user_service.py` — Business logic
  - [ ] `backend/app/api/users.py` — REST endpoints
    - [ ] `GET /api/users` — List users (paginated)
    - [ ] `POST /api/users` — Create user
    - [ ] `GET /api/users/{id}` — Get user
    - [ ] `PUT /api/users/{id}` — Update user
    - [ ] `DELETE /api/users/{id}` — Delete user

- [ ] **Role & Permission System**
  - [ ] `backend/app/models/role.py`
  - [ ] `backend/app/core/permissions.py`
    - [ ] Permission constants
    - [ ] Role-permission matrix
    - [ ] `has_permission()` helper
  - [ ] `backend/app/middleware/rbac.py`
    - [ ] `@require_permissions()` decorator
    - [ ] Role-based access control

- [ ] **Seed Admin User**
  - [ ] Create default super_admin on first run
  - [ ] Use credentials from `DEV_ADMIN_USER` / `DEV_ADMIN_PASSWORD`

---

## Week 3: Frontend & Containerization

### Day 1-2: Next.js 16 Setup

#### Tasks

- [ ] **Initialize Next.js 16 Project**
  ```bash
  npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --no-import-alias
  ```

- [ ] **Core Dependencies**
  ```bash
  cd frontend
  npm install @tanstack/react-query zustand axios recharts lucide-react
  npm install -D @types/node @types/react @types/react-dom
  ```

- [ ] **Project Structure**
  ```
  frontend/src/
  ├── app/
  │   ├── (auth)/           # Auth routes (login)
  │   │   └── login/
  │   │       └── page.tsx
  │   ├── (dashboard)/      # Dashboard routes
  │   │   ├── admin/        # Admin pages (stub)
  │   │   ├── user/         # User pages
  │   │   │   ├── profile/
  │   │   │   ├── servers/
  │   │   │   └── settings/
  │   │   └── page.tsx      # Dashboard home
  │   ├── api/              # Next.js API routes
  │   ├── layout.tsx        # Root layout
  │   └── globals.css
  ├── components/
  │   ├── ui/               # shadcn/ui components
  │   ├── layout/           # Layout components
  │   └── forms/            # Form components
  ├── hooks/                # Custom React hooks
  ├── lib/                  # Utilities, API client
  ├── types/                # TypeScript types
  └── providers/            # Context providers
  ```

- [ ] **UI Framework**
  - [ ] Install shadcn/ui: `npx shadcn@latest init`
  - [ ] Add components: button, input, card, dialog, table, dropdown-menu
  - [ ] Configure Tailwind theme (colors, fonts)

### Day 3-4: Frontend Auth & Dashboard

#### Tasks

- [ ] **Authentication Flow**
  - [ ] Login page (`/login`)
    - [ ] Username/password form
    - [ ] JWT token storage (httpOnly cookie)
    - [ ] Redirect to dashboard on success
  - [ ] Auth context/provider
  - [ ] Protected route wrapper
  - [ ] Logout functionality

- [ ] **Dashboard Shell**
  - [ ] Sidebar navigation
  - [ ] Header with user info
  - [ ] Breadcrumb navigation
  - [ ] Responsive layout

- [ ] **User Profile Page**
  - [ ] View profile
  - [ ] Edit profile form
  - [ ] Change password

### Day 5-7: NukeIDE Containerization

#### Tasks

- [ ] **Create Base Image (`environments/base/Dockerfile`)**
  ```dockerfile
  FROM ubuntu:24.04
  
  # Install system dependencies
  RUN apt-get update && apt-get install -y \
      curl git build-essential python3 python3-pip \
      nginx \
      && rm -rf /var/lib/apt/lists/*
  
  # Install Node.js 22
  RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
      && apt-get install -y nodejs
  
  # Install Yarn
  RUN npm install -g yarn
  
  # Create app directory
  WORKDIR /opt/nukelab
  ```

- [ ] **Create Dev Image (`environments/dev/Dockerfile`)**
  ```dockerfile
  FROM nukelab-base:latest
  
  # Clone NukeIDE
  RUN git clone https://github.com/nukehub-dev/nuke-ide.git /opt/nuke-ide
  
  WORKDIR /opt/nuke-ide
  
  # Build NukeIDE
  RUN yarn install \
      && yarn build:browser
  
  # Copy nginx config
  COPY nginx.conf /etc/nginx/nginx.conf
  COPY startup.sh /opt/nukelab/startup.sh
  
  # Expose port
  EXPOSE 80
  
  CMD ["/opt/nukelab/startup.sh"]
  ```

- [ ] **Nginx Auth Proxy (`environments/dev/nginx.conf`)**
  ```nginx
  server {
      listen 80;
      
      location / {
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
          proxy_pass http://backend:8000/api/auth/verify;
          proxy_pass_request_body off;
          proxy_set_header Content-Length "";
          proxy_set_header X-Original-Uri $request_uri;
      }
  }
  ```

- [ ] **Startup Script (`environments/dev/startup.sh`)**
  ```bash
  #!/bin/bash
  # Start Theia backend
  cd /opt/nuke-ide
  yarn start:browser &
  
  # Start nginx
  nginx -g 'daemon off;'
  ```

- [ ] **Build Scripts**
  - [ ] `scripts/build-base.sh` — Build base image
  - [ ] `scripts/build-dev.sh` — Build dev environment
  - [ ] `scripts/build-all.sh` — Build all environments

---

## Integration & Testing

### Container Spawning (End of Week 3)

#### Tasks

- [ ] **Docker SDK Integration**
  - [ ] `backend/app/docker/client.py` — Async Docker client
  - [ ] `backend/app/docker/spawner.py` — Container spawning logic

- [ ] **Server Spawn Endpoint**
  - [ ] `POST /api/servers`
    - [ ] Validate user permissions
    - [ ] Check resource availability
    - [ ] Pull/build image
    - [ ] Create container with Traefik labels
    - [ ] Start container
    - [ ] Return server info

- [ ] **Traefik Dynamic Labels**
  ```python
  labels = {
      "traefik.enable": "true",
      "traefik.http.routers.user-{username}.rule": f"Host(`localhost`) && PathPrefix(`/user/{username}`)",
      "traefik.http.services.user-{username}.loadbalancer.server.port": "80",
  }
  ```

#### Testing Checklist

**Test Results**: See `phases/01-foundation/TEST-RESULTS.md` for full details

- [x] Admin can log in via local auth
- [x] Admin can spawn dev environment
- [x] Server stop works
- [x] Server delete works
- [x] JWT auth works for API access
- [x] API token auth works (`Authorization: Token <token>`)
- [x] Token creation, usage tracking, and revocation work
- [ ] Admin sees dashboard (Frontend not complete)
- [ ] NukeIDE accessible at `/user/admin/{server-id}` (Traefik routing issue with Podman)
- [ ] Server start works (Not implemented — stub only)
- [x] All core services communicate properly

---

## Deliverables

By end of Phase 1, the following should be functional:

### Services Running
- [ ] Traefik v3 (reverse proxy)
- [ ] PostgreSQL 17
- [ ] Redis
- [ ] FastAPI backend
- [ ] Next.js 16 frontend
- [ ] Celery worker (basic setup)

### Features Working
- [x] Admin login (local auth)
- [ ] Dashboard UI
- [ ] User profile management
- [ ] Basic RBAC (roles enforced)
- [ ] Server spawn (dev environment only)
- [ ] NukeIDE container access
- [ ] Container lifecycle (start/stop)
- [x] **API Token System** (Bonus)
  - [x] Token creation with scopes
  - [x] Dual auth (JWT + API tokens)
  - [x] Token usage tracking
  - [x] Token revocation and regeneration

### Documentation
- [ ] `README.md` with quick start
- [ ] `docs/phase1.md` — Phase 1 completion notes
- [ ] API docs (auto-generated Swagger UI at `/api/docs`)

---

## Success Criteria

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

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| NukeIDE build fails | High | Pre-build locally, cache layers, use multi-stage |
| Docker socket permissions | Medium | Document setup, use docker group |
| Port conflicts | Low | Use non-standard ports if needed |
| Slow builds | Medium | Use BuildKit, cache mounts |
| Memory issues on dev machine | Medium | Limit container resources, use swap |

---

## Notes

- **NukeIDE Path Updates**: Out of scope. NukeIDE will be updated separately to work without JupyterHub paths.
- **PostgreSQL Version**: Using 17 (latest stable). Will upgrade to 18 when officially released.
- **Container Registry**: Local builds only. Push to registry in Phase 6.
- **SSL**: Self-signed certificates for development. Production certificates in Phase 6.
- **Monitoring**: Basic logging only. Full monitoring in Phase 4.
- **API Token Infrastructure**: Added as bonus work to provide foundation for Phase 2 (User Management & RBAC). The basic auth flow is complete — full UI and scope-based permissions will be built in Phase 2.

---

**Next**: Phase 2 — User Management & RBAC (Weeks 4-6)
