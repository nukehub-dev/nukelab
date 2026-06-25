# NukeLab Platform v2.0

Multi-user scientific computing platform with granular RBAC, real-time monitoring, and credit-based resource management.

[![CI/CD](https://github.com/nukehub-dev/nukelab/actions/workflows/ci.yml/badge.svg)](https://github.com/nukehub-dev/nukelab/actions/workflows/ci.yml)
[![Security Scans](https://github.com/nukehub-dev/nukelab/actions/workflows/security.yml/badge.svg)](https://github.com/nukehub-dev/nukelab/actions/workflows/security.yml)

**Status**: Active Development  
**Last Updated**: June 7, 2026

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
./nukelabctl start
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
./nukelabctl start
```

### Manual Start (without nukelabctl)

```bash
# Docker
docker-compose up -d

# Podman
podman-compose up -d
```

## Using Podman

The project automatically detects Podman and configures the correct socket path. Just run:

```bash
./nukelabctl start
```

The script will:
- Auto-detect Podman vs Docker
- Set the correct socket path (`/run/user/1000/podman/podman.sock`)
- Use `podman-compose` if available

## Development Mode

For full local development with hot reload:

```bash
./nukelabctl dev              # start dev stack
./nukelabctl dev restart      # restart dev stack
./nukelabctl dev logs backend # stream backend logs
./nukelabctl dev stop         # stop dev stack
```

This starts:
- Backend containers (API, PostgreSQL, Redis, Celery) with auto-reload
- Frontend Vite dev server on http://localhost:5173

The dev stack uses the same container names as the production stack, so only
one may be running at a time. `start` and `dev start` will refuse to run if the
other stack is already up. `stop`, `logs`, and `status` always operate on the
stack matching the command you run.

Or run frontend separately:

```bash
cd frontend
npm install
npm run dev
```



## Management Commands

```bash
./nukelabctl start          # Start all services
./nukelabctl stop           # Stop all services
./nukelabctl restart        # Restart all services
./nukelabctl build          # Rebuild containers
./nukelabctl logs [service] # View logs (backend, frontend, etc.)
./nukelabctl status         # Show running containers
```

## CI/CD

The repository uses GitHub Actions for continuous integration and delivery:

- **`.github/workflows/ci.yml`** — lints backend/frontend, runs backend tests, builds container images, and pushes them to GitHub Container Registry on pushes to `main`/`develop`.
- **`.github/workflows/security.yml`** — runs Bandit, `pip-audit`, and `npm audit` on every push/PR and weekly.

Pushed images:

```text
ghcr.io/nukehub-dev/nukelab-backend:<version>
ghcr.io/nukehub-dev/nukelab-frontend:<version>
ghcr.io/nukehub-dev/nukelab-auth-sidecar:<version>
```

Tags applied depend on the branch/tag:

| Git ref | Tags | `latest` |
|---|---|---|
| `v1.2.3` tag | `1.2.3`, `sha-abc1234` | yes |
| `main` branch | `main`, `sha-abc1234` | yes |
| `develop` branch | `develop`, `sha-abc1234` | no |
| Pull request | `pr-42`, `sha-abc1234` | no |

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
├── frontend/                # Vite + React 19 SPA
├── environments/            # Docker images
│   ├── base/               # Shared base image
│   └── dev/                # NukeIDE dev environment
├── database/                # Schema and migrations
├── phases/                 # Implementation phases
├── compose.yml             # All services
├── nukelabctl               # Management script (Docker/Podman)
└── README.md
```

## Architecture

- **Reverse Proxy**: Traefik v3
- **Frontend**: Vite + React 19 SPA
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

- [Operations Guide](docs/OPERATIONS.md) — Database profiling, backup/restore, scaling
- [Backup & Restore](docs/BACKUP-RESTORE.md) — Disaster recovery procedures
- [Production Deployment](docs/PRODUCTION-DEPLOYMENT.md) — Production setup guide
- [Read Replicas](docs/READ-REPLICAS.md) — Future scaling reference (not yet implemented)
- [Phase 1 Plan](phases/01-foundation/PLAN.md)
- [Phase 2 Plan](phases/02-user-management/PLAN.md)
- [Phase 3 Plan](phases/03-environment-resource-management/PLAN.md)
- [Full Architecture Plan](PLAN.md)
- [Phase Review Report](phases/REVIEW-REPORT.md)

## License

BSD-2-Clause
