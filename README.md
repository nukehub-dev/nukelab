# NukeLab Platform v2.0

Multi-user scientific computing platform with granular RBAC, real-time monitoring, and credit-based resource management.

**Status**: Active Development (Phases 1-4 Complete)  
**Last Updated**: April 29, 2026

## Quick Start

### Prerequisites

- **Container Engine**: Docker or Podman
- **Compose**: docker-compose or podman-compose
- **Git**
- 10GB+ free disk space

### Environment Files

| File | Purpose | Committed |
|------|---------|-----------|
| `.env.example` | Template with all variables | ✅ Yes |
| `.env.development` | Development config | ❌ No (ignored) |
| `.env` | Production secrets | ❌ No (ignored) |

### Development Setup

```bash
# Clone repository
git clone https://github.com/nukehub-dev/nukelab.git
cd nukelab
git checkout new

# Create development environment file
cp .env.example .env.development

# Start services
./manage.sh start
```

**Access points:**
- Frontend: http://localhost:8080
- API: http://localhost:8080/api
- API Docs: http://localhost:8080/api/docs

**Default login:**
- Username: `admin`
- Password: `admin123`

### Production Setup

```bash
cp .env.example .env
# Edit .env with your production secrets
vim .env

# Start services
./manage.sh start
```

### Manual Start (without manage.sh)

```bash
# Docker
docker-compose up -d

# Podman
podman-compose up -d
```

## Using Podman

The project automatically detects Podman and configures the correct socket path. Just run:

```bash
./manage.sh start
```

The script will:
- Auto-detect Podman vs Docker
- Set the correct socket path (`/run/user/1000/podman/podman.sock`)
- Use `podman-compose` if available

## Development Mode

For full local development with hot reload:

```bash
./manage.sh start --dev
```

This starts:
- Backend containers (API, PostgreSQL, Redis, Celery) with auto-reload
- Frontend Vite dev server on http://localhost:5173

Or run frontend separately:

```bash
cd frontend
npm install
npm run dev
```

## Management Commands

```bash
./manage.sh start          # Start all services
./manage.sh stop           # Stop all services
./manage.sh restart        # Restart all services
./manage.sh build          # Rebuild containers
./manage.sh logs [service] # View logs (backend, frontend, etc.)
./manage.sh status         # Show running containers
```

## Project Structure

```
nukelab/
├── backend/                 # FastAPI application
│   ├── app/
│   │   ├── api/            # REST API routes
│   │   ├── db/             # Database models & session
│   │   ├── models/         # SQLAlchemy models
│   │   ├── config.py       # Configuration
│   │   └── main.py         # FastAPI app
│   ├── Dockerfile
│   └── requirements.txt     # Pip dependencies
├── frontend/                # Next.js 16 application
├── environments/            # Docker images
│   ├── base/               # Shared base image
│   └── dev/                # NukeIDE dev environment
├── database/                # Schema and migrations
├── phases/                 # Implementation phases
├── compose.yml             # All services
├── manage.sh               # Management script (Docker/Podman)
└── README.md
```

## Architecture

- **Reverse Proxy**: Traefik v3
- **Frontend**: Next.js 16 (App Router)
- **Backend**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 17
- **Cache**: Redis
- **Task Queue**: Celery
- **Container Engine**: Docker or Podman

## API Endpoints

The platform exposes 52+ REST API endpoints. Auto-generated docs available at `/api/docs`.

### Authentication
- `POST /api/auth/login` - User login (returns JWT token)
- `GET /api/auth/me` - Get current user profile

### Users
- `GET /api/users/` - List users (admin/moderator)
- `POST /api/users/` - Create user (admin/moderator)
- `GET /api/users/{id}` - Get user details
- `PUT /api/users/{id}` - Update user profile
- `DELETE /api/users/{id}` - Delete user (admin)
- `POST /api/users/{id}/disable` - Disable/enable user with reason

### Servers
- `GET /api/servers/` - List user's servers
- `POST /api/servers/` - Spawn new server
- `POST /api/servers/{id}/start` - Start server
- `POST /api/servers/{id}/stop` - Stop server
- `POST /api/servers/{id}/restart` - Restart server
- `DELETE /api/servers/{id}` - Delete server

### Environments
- `GET /api/environments/` - List environment templates
- `POST /api/environments/` - Create environment (admin)
- `PUT /api/environments/{id}` - Update environment (admin)
- `DELETE /api/environments/{id}` - Deactivate environment (admin)
- `DELETE /api/environments/{id}/permanent` - Permanently delete (admin)
- `POST /api/environments/{id}/activate` - Activate environment (admin)
- `POST /api/environments/{id}/clone` - Clone environment (admin)

### Plans
- `GET /api/plans/` - List server plans
- `POST /api/plans/` - Create plan (admin)
- `PUT /api/plans/{id}` - Update plan (admin)
- `DELETE /api/plans/{id}` - Deactivate plan (admin)
- `DELETE /api/plans/{id}/permanent` - Permanently delete (admin)
- `POST /api/plans/{id}/activate` - Activate plan (admin)

### Credits
- `GET /api/credits/` - Get current user credits
- `GET /api/credits/history` - Credit transaction history
- `POST /api/credits/users/{id}/grant` - Grant credits (admin)
- `POST /api/credits/users/{id}/deduct` - Deduct credits (admin)

### Quotas
- `GET /api/quotas/` - Get current user's resource quota
- `POST /api/quotas/check` - Check if spawn is allowed

### Metrics & Monitoring
- `GET /api/metrics/system/latest` - Latest system metrics
- `GET /api/metrics/system` - System metrics history
- `GET /api/metrics/servers/{id}` - Server metrics history
- `GET /api/metrics/servers/{id}/latest` - Latest server metrics
- `GET /api/metrics/alerts/rules` - List alert rules
- `POST /api/metrics/alerts/rules` - Create alert rule
- `GET /api/metrics/alerts/history` - Alert history
- `GET /api/metrics/health/summary` - Health summary
- `WS /ws` - Real-time metrics WebSocket

### Admin
- `GET /api/admin/stats` - Dashboard statistics
- `GET /api/admin/users` - Admin user listing
- `POST /api/admin/credits/grant-bulk` - Bulk credit grant
- `GET /api/admin/activity` - Activity logs

## Documentation

- [Phase 1 Plan](phases/01-foundation/PLAN.md)
- [Phase 2 Plan](phases/02-user-management/PLAN.md)
- [Phase 3 Plan](phases/03-environment-resource-management/PLAN.md)
- [Full Architecture Plan](PLAN.md)
- [Phase Review Report](phases/REVIEW-REPORT.md)

## License

BSD-2-Clause
