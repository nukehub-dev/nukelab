# Local Development

This guide covers how to run NukeLab locally for development and debugging.

## Prerequisites

- Docker or Podman
- docker-compose or podman-compose
- Git
- 10 GB free disk space
- Node.js 22 and npm (only if running the frontend outside containers)

## Initial setup

```bash
git clone https://github.com/nukehub-dev/nukelab.git
cd nukelab
cp .env.example .env.development
```

Edit `.env.development` if you need to change ports, credentials, or feature flags. The defaults are sufficient for most local work.

## Start the development stack

```bash
./nukelabctl dev
```

This starts:

- Backend API, PostgreSQL, Redis, and Celery workers with auto-reload
- Frontend Vite dev server on <http://localhost:5173>

The dev stack uses the same container names as the production stack. `start` and `dev start` refuse to run if the other stack is already up.

## Useful dev commands

```bash
./nukelabctl dev start        # Start dev stack
./nukelabctl dev restart      # Restart dev stack
./nukelabctl dev logs backend # Stream backend logs
./nukelabctl dev logs frontend# Stream frontend logs
./nukelabctl dev stop         # Stop dev stack
```

## Run the frontend separately

If you prefer to run the frontend directly on the host for faster iteration:

```bash
cd frontend
npm install
npm run dev
```

Set `FRONTEND_URL=http://localhost:5173` in `.env.development` so the backend knows where to redirect or link.

## Default development login

When `DEV_MODE=true`, the first startup creates:

- Username: `admin`
- Password: `admin123`

Change these in `.env.development` or create additional users through the admin UI.

## Access points

| Service | Production stack | Development stack |
|---|---|---|
| Frontend | <http://localhost:8080> | <http://localhost:5173> |
| API | <http://localhost:8080/api> | <http://localhost:8080/api> |
| API docs | <http://localhost:8080/api/docs> | <http://localhost:8080/api/docs> |

## Container engine notes

### Docker

Works out of the box. The backend auto-detects `/var/run/docker.sock`.

### Podman

The project auto-detects Podman and configures the correct socket path (typically `/run/user/1000/podman/podman.sock`). No manual configuration is required.

For rootless Podman with cgroup-aware resource limits, you may need to delegate controllers:

```bash
sudo mkdir -p /etc/systemd/system/user@.service.d/
sudo tee /etc/systemd/system/user@.service.d/delegate.conf << 'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
sudo systemctl daemon-reload
```

Log out and back in for the change to take effect.

## Running tests

```bash
# Backend tests inside the test container
./nukelabctl test all

# Backend tests scoped to a file or directory
./nukelabctl test backend tests/api/servers/test_servers.py -x -v

# Frontend unit tests
cd frontend
npm run test
```

## Linting and formatting

```bash
./nukelabctl lint all       # ruff + eslint/prettier + shellcheck/shfmt
./nukelabctl lint all --fix # Auto-fix where supported
./nukelabctl selftest       # nukelabctl sanity check
```

## Troubleshooting

### Port already in use

Make sure no other stack is running:

```bash
./nukelabctl status
./nukelabctl stop
./nukelabctl dev stop
```

### Backend container fails to connect to Docker/Podman

Check that `DOCKER_SOCKET` in `.env.development` matches your active socket, or leave it empty for auto-detection.

### Database schema out of date

The backend applies migrations on startup. To force a fresh migration:

```bash
./nukelabctl exec backend alembic upgrade head
```

## Related documents

- [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow
- [reference/ENV-VARS.md](../reference/ENV-VARS.md) for environment variable reference
- [reference/CLI-COMMANDS.md](../reference/CLI-COMMANDS.md) for `nukelabctl` commands
- [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for production setup differences
