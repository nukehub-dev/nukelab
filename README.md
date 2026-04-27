# NukeLab Platform v2.0

Multi-user scientific computing platform with granular RBAC, real-time monitoring, and credit-based resource management.

## Quick Start

### Prerequisites

- **Container Engine**: Docker or Podman
- **Compose**: docker-compose or podman-compose
- **Git**
- **Optional**: Conda (for local Python development)
- 10GB+ free disk space

### Setup

1. **Clone and configure:**
   ```bash
   git clone https://github.com/nukehub-dev/nukelab.git
   cd nukelab
   git checkout new
   cp .env.development .env
   ```

2. **Start services:**
   ```bash
   ./manage.sh start
   ```
   
   Or manually:
   ```bash
   # Docker
   docker-compose up -d
   
   # Podman
   podman-compose up -d
   ```

3. **Access the application:**
   - Frontend: http://localhost
   - API Docs: http://localhost/api/docs
   - Traefik Dashboard: http://localhost:8080

4. **Login with default admin:**
   - Username: `admin`
   - Password: `admin123`

### Using Conda for Development

If you prefer using Conda instead of Docker for the backend:

```bash
# Setup Conda environment
./manage.sh conda-setup

# Activate and run backend locally
conda activate nukelab-backend
cd backend
uvicorn app.main:app --reload --port 8000
```

The `environment.yml` in `backend/` defines all Python dependencies.

### Using Podman

The project automatically detects Podman and configures the correct socket path. Just run:

```bash
./manage.sh start
```

The script will:
- Auto-detect Podman vs Docker
- Set the correct socket path (`/run/podman/podman.sock`)
- Use `podman-compose` if available

### Development Mode

For full local development with hot reload:

**Terminal 1 - Backend (Conda):**
```bash
./manage.sh conda-run
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Terminal 3 - Infrastructure:**
```bash
# Start only PostgreSQL and Redis
docker-compose up -d postgres redis
# or
podman-compose up -d postgres redis
```

## Management Commands

```bash
./manage.sh start          # Start all services
./manage.sh stop           # Stop all services
./manage.sh restart        # Restart all services
./manage.sh build          # Rebuild containers
./manage.sh logs [service] # View logs (backend, frontend, etc.)
./manage.sh status         # Show running containers
./manage.sh conda-setup    # Setup Conda environment
./manage.sh conda-run      # Run backend with Conda
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
│   ├── requirements.txt     # Pip dependencies
│   └── environment.yml      # Conda environment
├── frontend/                # Next.js 16 application
├── environments/            # Docker images
│   ├── base/               # Shared base image
│   └── dev/                # NukeIDE dev environment
├── database/                # Schema and migrations
├── phases/                 # Implementation phases
├── docker-compose.yml      # All services
├── manage.sh               # Management script (Docker/Podman/Conda)
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

## Documentation

- [Phase 1 Plan](phases/01-foundation/PLAN.md)
- [Full Architecture Plan](PLAN.md)

## License

BSD-2-Clause
