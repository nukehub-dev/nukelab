#!/bin/bash

# NukeLab Platform v2.0 — Unified Management Script
# Usage: ./manage.sh <command> [target] [flags]
#
# Examples:
#   ./manage.sh start                    # Start production stack (containers)
#   ./manage.sh start --dev              # Start dev stack (backend containers + Vite)
#   ./manage.sh start backend --conda    # Start backend via Conda (no containers)
#   ./manage.sh stop                     # Stop everything
#   ./manage.sh stop frontend            # Stop only frontend dev server
#   ./manage.sh build                    # Build all containers
#   ./manage.sh build frontend           # Build only frontend container
#   ./manage.sh update                   # Pull latest images and rebuild
#   ./manage.sh clean                    # Remove dangling images/volumes
#   ./manage.sh shell backend            # Open shell in backend container
#   ./manage.sh db-migrate               # Run database migrations
#   ./manage.sh test                     # Run tests
#   ./manage.sh restart backend          # Restart backend only
#   ./manage.sh status                   # Show status of everything
#   ./manage.sh logs backend             # Stream backend logs
#   ./manage.sh install                  # Install all dependencies
#   ./manage.sh install frontend         # Install only frontend deps
#   ./manage.sh reset                    # ⚠️ Reset everything

set -euo pipefail

# ─── Colors ────────────────────────────────────────────────────────────────
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
MAGENTA=$'\033[0;35m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RESET=$'\033[0m'

# ─── Setup ─────────────────────────────────────────────────────────────────
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"
cd "$DIR"
FRONTEND_PID_FILE="$DIR/.frontend.pid"
COMPOSE_FILE="$DIR/docker-compose.yml"

# ─── Helpers ───────────────────────────────────────────────────────────────
log()   { echo -e "${BLUE}▶${RESET} $*"; }
info()  { echo -e "${CYAN}ℹ${RESET}  $*"; }
ok()    { echo -e "${GREEN}✓${RESET}  $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
err()   { echo -e "${RED}✗${RESET}  $*" >&2; }
die()   { err "$*"; exit 1; }
step()  { echo -e "\n${BOLD}${MAGENTA}▸${RESET} ${BOLD}$*${RESET}"; }

# ─── Argument Parsing ──────────────────────────────────────────────────────
CMD=""
TARGET=""
USE_DEV_MODE=false
USE_CONDA_MODE=false
EXTRA_ARGS=()

parse_args() {
    CMD="${1:-help}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            backend|frontend|all)
                TARGET="$1"
                ;;
            --dev|-d)
                USE_DEV_MODE=true
                ;;
            --conda|-c)
                USE_CONDA_MODE=true
                ;;
            --help|-h)
                print_help
                exit 0
                ;;
            --*)
                EXTRA_ARGS+=("$1")
                ;;
            *)
                if [[ -z "$TARGET" ]]; then
                    TARGET="$1"
                else
                    EXTRA_ARGS+=("$1")
                fi
                ;;
        esac
        shift
    done

    if [[ -z "$TARGET" ]]; then
        TARGET="all"
    fi
}

# ─── Environment ───────────────────────────────────────────────────────────
load_env_file() {
    local env_file="$1"
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip pure comment lines
        if [[ "$line" =~ ^[[:space:]]*#.*$ ]]; then
            continue
        fi
        # Skip empty lines
        if [[ -z "${line// /}" ]]; then
            continue
        fi
        # Strip inline comments: remove everything from first # onwards
        local cleaned="${line%%#*}"
        # Trim trailing whitespace
        while [[ "$cleaned" == *[[:space:]] ]]; do
            cleaned="${cleaned%[[:space:]]}"
        done
        export "$cleaned" 2>/dev/null || true
    done < "$env_file"
}

init_env() {
    # Always load .env as base defaults
    if [ -f .env ]; then
        log "Loading ${BOLD}.env${RESET}"
        load_env_file .env
    fi
    # In dev mode, overlay .env.development on top so dev values win
    if $USE_DEV_MODE && [ -f .env.development ]; then
        log "Loading ${BOLD}.env.development${RESET} (dev overrides)"
        load_env_file .env.development
    elif [ ! -f .env ] && [ -f .env.development ]; then
        log "Loading ${BOLD}.env.development${RESET}"
        load_env_file .env.development
    elif [ ! -f .env ] && [ ! -f .env.development ]; then
        die "No environment file found.\n\n  cp .env.example .env.development"
    fi
}

# ─── Container Engine ──────────────────────────────────────────────────────
detect_engine() {
    if command -v podman > /dev/null 2>&1; then
        CONTAINER_ENGINE=podman
        info "Podman detected"
    elif command -v docker > /dev/null 2>&1; then
        CONTAINER_ENGINE=docker
        info "Docker detected"
    else
        die "Neither podman nor docker found"
    fi

    if command -v podman-compose > /dev/null 2>&1; then
        COMPOSE="podman-compose"
    elif command -v docker-compose > /dev/null 2>&1; then
        COMPOSE="docker-compose"
    elif $CONTAINER_ENGINE compose version > /dev/null 2>&1; then
        COMPOSE="$CONTAINER_ENGINE compose"
    else
        die "No compose command found"
    fi
}

setup_podman_socket() {
    [ "$CONTAINER_ENGINE" != "podman" ] && return

    # If DOCKER_SOCKET is set but doesn't exist, override it
    if [ -n "${DOCKER_SOCKET:-}" ] && [ ! -S "$DOCKER_SOCKET" ]; then
        warn "DOCKER_SOCKET=$DOCKER_SOCKET not found, auto-detecting..."
        unset DOCKER_SOCKET
    fi

    # Auto-detect if not set
    if [ -z "${DOCKER_SOCKET:-}" ]; then
        SOCK=$(podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null || true)
        if [ -n "$SOCK" ]; then
            export DOCKER_SOCKET="$SOCK"
        elif [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/podman/podman.sock" ]; then
            export DOCKER_SOCKET="$XDG_RUNTIME_DIR/podman/podman.sock"
        else
            export DOCKER_SOCKET="/run/podman/podman.sock"
        fi
        info "Using Podman socket: $DOCKER_SOCKET"
    fi

    export DOCKER_NUKELAB_HOST="$DOCKER_SOCKET"
}

# ─── Frontend Process Utils ────────────────────────────────────────────────
is_frontend_running() {
    [ -f "$FRONTEND_PID_FILE" ] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null
}

kill_frontend() {
    if is_frontend_running; then
        local pid=$(cat "$FRONTEND_PID_FILE")
        log "Stopping frontend (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        rm -f "$FRONTEND_PID_FILE"
        ok "Frontend stopped"
    fi
}

# ─── Backend Detection ─────────────────────────────────────────────────────
is_backend_container_running() {
    $COMPOSE -f "$COMPOSE_FILE" ps 2>/dev/null | grep -q 'Up .*nukelab-backend'
}

# ─── CPU Lib Volume ────────────────────────────────────────────────────────
setup_cpu_lib_volume() {
    local vol_name="nukelab-cpu-lib"
    local c_file="$DIR/backend/app/lib/nukelab/libnukelab_cpu.c"

    if [ ! -f "$c_file" ]; then
        warn "CPU mask source not found: $c_file"
        return
    fi

    # Skip if volume already exists
    if $CONTAINER_ENGINE volume inspect "$vol_name" > /dev/null 2>&1; then
        return
    fi

    step "Setting up CPU mask library..."

    # Create volume
    $CONTAINER_ENGINE volume create "$vol_name" > /dev/null
    ok "Created volume: $vol_name"

    # Build .so inside a temporary gcc container
    log "Building libnukelab_cpu.so (one-time)..."
    local tmp_name="nukelab-tmp-build-cpu-lib"
    local build_image="docker.io/library/gcc:latest"

    # Pull gcc image if not present
    if ! $CONTAINER_ENGINE image exists "$build_image" 2>/dev/null; then
        log "Pulling $build_image..."
        $CONTAINER_ENGINE pull "$build_image" > /dev/null 2>&1 || {
            warn "Failed to pull $build_image"
            warn "Check your internet connection or container registry access"
            return
        }
    fi

    # Create temp container with volume mounted
    $CONTAINER_ENGINE run --rm -d \
        --name "$tmp_name" \
        -v "$vol_name:/dst" \
        -v "$c_file:/src/libnukelab_cpu.c:ro" \
        "$build_image" \
        sleep 3600 > /dev/null 2>&1 || {
        warn "Failed to start build container"
        return
    }

    # Compile
    $CONTAINER_ENGINE exec "$tmp_name" \
        gcc -shared -fPIC -o /dst/libnukelab_cpu.so /src/libnukelab_cpu.c -ldl

    local exit_code=$?
    $CONTAINER_ENGINE rm -f "$tmp_name" > /dev/null 2>&1

    if [ $exit_code -ne 0 ]; then
        err "Failed to build libnukelab_cpu.so"
        $CONTAINER_ENGINE volume rm "$vol_name" > /dev/null 2>&1 || true
        return
    fi

    ok "Built and stored libnukelab_cpu.so in volume"
}

has_conda_env() {
    command -v conda > /dev/null 2>&1 && conda env list | grep -q "nukelab-backend"
}

# ─── Health Check ──────────────────────────────────────────────────────────
wait_for_backend() {
    local url="${APP_URL:-http://localhost:8080}/api/health"
    local waited=0
    step "Waiting for backend..."
    while ! curl -sf "$url" > /dev/null 2>&1; do
        sleep 2
        waited=$((waited + 2))
        [ "$waited" -ge 60 ] && { warn "Timeout, continuing..."; return 1; }
        printf "."
    done
    ok "Backend ready (${waited}s)"
}

# ─── Command Implementations ───────────────────────────────────────────────

cmd_start() {
    setup_cpu_lib_volume

    if $USE_CONDA_MODE; then
        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            die "--conda only works with backend target. Use:\n  ./manage.sh start backend --conda"
        fi
        step "Starting backend with Conda..."
        command -v conda > /dev/null 2>&1 || die "Conda not found"
        conda env list | grep -q "nukelab-backend" || die "Run: ./manage.sh install backend"
        cd "$DIR/backend"
        conda run -n nukelab-backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
        return
    fi

    init_env

    if $USE_DEV_MODE; then
        step "Starting development stack..."

        # In dev mode, frontend runs on Vite dev server (port 5173)
        # This tells the backend where to redirect after OAuth login
        export FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"
        info "FRONTEND_URL=$FRONTEND_URL"

        $COMPOSE -f "$COMPOSE_FILE" stop frontend 2>/dev/null || true

        if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
            log "Starting backend containers..."
            $COMPOSE -f "$COMPOSE_FILE" up -d traefik postgres redis backend celery-worker celery-beat
            wait_for_backend
        fi

        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            command -v npm > /dev/null 2>&1 || die "npm not found"
            [ -d "$DIR/frontend/node_modules" ] || die "Run: ./manage.sh install frontend"
            log "Starting Vite dev server..."

            cd "$DIR/frontend"
            npm run dev &
            echo $! > "$FRONTEND_PID_FILE"
            ok "Frontend started on ${CYAN}http://localhost:5173${RESET}"
        fi
        
        echo ""
        ok "Development stack running!"
        echo -e "  Frontend: ${CYAN}http://localhost:5173${RESET} ${DIM}(Vite dev)${RESET}"
        echo -e "  API:      ${CYAN}http://localhost:8080/api${RESET}"
        echo -e "  Traefik:  ${CYAN}http://localhost:8090${RESET}"
        echo -e "\n  ${YELLOW}Ctrl+C to stop${RESET}"
        
        trap 'echo ""; step "Shutting down..."; kill_frontend; $COMPOSE -f "$COMPOSE_FILE" down; ok "Goodbye!"; exit 0' INT TERM
        wait
    else
        step "Starting production stack..."
        
        if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
            log "Starting backend services..."
            $COMPOSE -f "$COMPOSE_FILE" up -d traefik postgres redis backend celery-worker celery-beat
        fi
        
        if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
            log "Starting frontend container..."
            $COMPOSE -f "$COMPOSE_FILE" up -d frontend
        fi
        
        ok "Stack running!"
        echo -e "  URL: ${CYAN}http://localhost:8080${RESET}"
        echo -e "  API: ${CYAN}http://localhost:8080/api${RESET}"
    fi
}

cmd_stop() {
    step "Stopping services..."
    
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE -f "$COMPOSE_FILE" stop frontend 2>/dev/null || true
    fi
    
    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE -f "$COMPOSE_FILE" stop traefik postgres redis backend celery-worker celery-beat 2>/dev/null || true
    fi
    
    ok "Stopped"
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

cmd_build() {
    setup_cpu_lib_volume

    step "Building..."
    
    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        log "Building backend containers..."
        $COMPOSE -f "$COMPOSE_FILE" build backend celery-worker celery-beat
    fi
    
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        log "Building frontend container..."
        $COMPOSE -f "$COMPOSE_FILE" build frontend
    fi
    
    ok "Build complete"
}

cmd_update() {
    step "Updating NukeLab..."
    
    log "Pulling latest images..."
    $COMPOSE -f "$COMPOSE_FILE" pull
    
    log "Rebuilding containers..."
    $COMPOSE -f "$COMPOSE_FILE" build --no-cache
    
    ok "Update complete! Run './manage.sh restart' to apply changes."
}

cmd_pull() {
    step "Pulling latest images..."
    $COMPOSE -f "$COMPOSE_FILE" pull
    ok "Images pulled"
}

cmd_remove() {
    step "Removing containers..."
    
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        kill_frontend
        $COMPOSE -f "$COMPOSE_FILE" rm -f frontend 2>/dev/null || true
        ok "Frontend container removed"
    fi
    
    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        $COMPOSE -f "$COMPOSE_FILE" rm -f traefik postgres redis backend celery-worker celery-beat 2>/dev/null || true
        ok "Backend containers removed"
    fi
}

cmd_clean() {
    step "Cleaning up..."
    
    log "Removing stopped containers..."
    $CONTAINER_ENGINE container prune -f 2>/dev/null || true
    
    log "Removing dangling images..."
    $CONTAINER_ENGINE image prune -f 2>/dev/null || true
    
    log "Removing dangling volumes..."
    $CONTAINER_ENGINE volume prune -f 2>/dev/null || true
    
    log "Removing build cache..."
    $CONTAINER_ENGINE builder prune -f 2>/dev/null || true
    
    ok "Cleanup complete"
}

cmd_shell() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi
    
    step "Opening shell in ${BOLD}$service${RESET}..."
    
    case "$service" in
        backend)
            $COMPOSE -f "$COMPOSE_FILE" exec backend /bin/bash || \
            $COMPOSE -f "$COMPOSE_FILE" exec backend /bin/sh
            ;;
        postgres)
            $COMPOSE -f "$COMPOSE_FILE" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
            ;;
        redis)
            $COMPOSE -f "$COMPOSE_FILE" exec redis redis-cli
            ;;
        frontend)
            $COMPOSE -f "$COMPOSE_FILE" exec frontend /bin/sh
            ;;
        *)
            $COMPOSE -f "$COMPOSE_FILE" exec "$service" /bin/sh
            ;;
    esac
}

cmd_exec() {
    local service="${TARGET:-backend}"
    if [[ "$service" = "all" ]]; then
        service="backend"
    fi
    
    if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
        die "Usage: ./manage.sh exec <service> <command>\nExample: ./manage.sh exec backend ls -la"
    fi
    
    $COMPOSE -f "$COMPOSE_FILE" exec "$service" "${EXTRA_ARGS[@]}"
}

cmd_logs() {
    local service="${TARGET:-}"
    
    # In dev mode, frontend runs locally via Vite, not container
    if $USE_DEV_MODE && [[ "$service" == "" || "$service" == "all" ]]; then
        log "Dev mode: frontend runs locally via Vite (check terminal for output)"
        service="traefik postgres redis backend celery-worker celery-beat"
    fi
    
    $COMPOSE -f "$COMPOSE_FILE" logs -f ${service:-}
}

cmd_status() {
    step "Container Status"
    $COMPOSE -f "$COMPOSE_FILE" ps
    
    echo ""
    if is_frontend_running; then
        ok "Frontend dev: ${CYAN}http://localhost:5173${RESET} ${DIM}(PID: $(cat "$FRONTEND_PID_FILE"))${RESET}"
    else
        info "Frontend dev: ${DIM}not running${RESET}"
    fi
}

cmd_install() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Installing frontend dependencies..."
        command -v npm > /dev/null 2>&1 || die "npm not found"
        cd "$DIR/frontend"
        npm install
        ok "Frontend dependencies installed"
    fi
    
    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        step "Installing backend dependencies..."
        command -v conda > /dev/null 2>&1 || die "Conda not found"
        cd "$DIR/backend"
        if conda env list | grep -q "nukelab-backend"; then
            conda env update -f environment.yml --prune
        else
            conda env create -f environment.yml
        fi
        ok "Backend environment ready"
    fi
}

cmd_test() {
    if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "all" ]; then
        step "Running frontend tests..."
        cd "$DIR/frontend"
        [ -d "node_modules" ] || die "Run: ./manage.sh install frontend"
        npm run test 2>/dev/null || npm run lint || warn "No test script found"
    fi
    
    if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
        step "Running backend tests..."
        cd "$DIR/backend"
        
        if $USE_CONDA_MODE; then
            # User explicitly wants Conda
            has_conda_env || die "Conda env 'nukelab-backend' not found. Run: ./manage.sh install backend"
            conda run -n nukelab-backend pytest ${EXTRA_ARGS[@]:-} || warn "Tests failed or not configured"
        elif is_backend_container_running; then
            # Backend is running in containers, run tests there
            $COMPOSE -f "$COMPOSE_FILE" exec backend bash -c "PYTHONPATH=/app pytest ${EXTRA_ARGS[@]:-}" || warn "Tests failed or not configured"
        elif has_conda_env; then
            # Fall back to Conda
            conda run -n nukelab-backend pytest ${EXTRA_ARGS[@]:-} || warn "Tests failed or not configured"
        else
            die "Backend not running. Start it first:\n  ./manage.sh start backend\nOr install Conda env:\n  ./manage.sh install backend"
        fi
    fi
}

cmd_db_migrate() {
    step "Running database migrations..."
    
    if $USE_CONDA_MODE; then
        # User explicitly wants Conda
        has_conda_env || die "Conda env 'nukelab-backend' not found. Run: ./manage.sh install backend"
        cd "$DIR/backend"
        conda run -n nukelab-backend alembic upgrade head
    elif is_backend_container_running; then
        # Backend is running in containers, run migrations there
        $COMPOSE -f "$COMPOSE_FILE" exec backend alembic upgrade head
    elif has_conda_env; then
        # Fall back to Conda
        cd "$DIR/backend"
        conda run -n nukelab-backend alembic upgrade head
    else
        die "Backend not running. Start it first:\n  ./manage.sh start backend\nOr install Conda env:\n  ./manage.sh install backend"
    fi
    
    ok "Migrations applied"
}

cmd_db_shell() {
    step "Opening database shell..."
    $COMPOSE -f "$COMPOSE_FILE" exec postgres psql -U "${DATABASE_USER:-nukelab}" -d "${DATABASE_NAME:-nukelab}"
}

cmd_backup() {
    local backup_dir="$DIR/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/nukelab_backup_$timestamp.sql"
    
    mkdir -p "$backup_dir"
    step "Creating backup..."
    
    $COMPOSE -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "${DATABASE_USER:-nukelab}" "${DATABASE_NAME:-nukelab}" > "$backup_file"
    
    ok "Backup created: ${CYAN}$backup_file${RESET}"
}

cmd_reset() {
    step "${RED}${BOLD}WARNING:${RESET} This deletes ALL data and containers!"
    read -rp "Type 'yes' to confirm: " confirm
    [[ "$confirm" = "yes" ]] || { info "Aborted."; exit 0; }
    
    log "Stopping everything..."
    kill_frontend
    $COMPOSE -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
    $CONTAINER_ENGINE volume rm nukelab-postgres-data nukelab-letsencrypt 2>/dev/null || true
    ok "Reset complete"
}

# ─── Help ──────────────────────────────────────────────────────────────────
print_help() {
    cat <<-EOF
${BOLD}${CYAN}NukeLab v2.0${RESET} — Management Script

${BOLD}Usage:${RESET} ./manage.sh <command> [target] [flags]

${BOLD}${MAGENTA}Quick Start:${RESET}
  ${GREEN}start${RESET}      [target] [--dev]         Start services
  ${GREEN}stop${RESET}       [target]                  Stop services
  ${GREEN}restart${RESET}    [target] [--dev]         Restart services
  ${GREEN}status${RESET}                               Show status

${BOLD}Build & Deploy:${RESET}
  ${GREEN}build${RESET}      [target]                  Build containers
  ${GREEN}update${RESET}                               Pull images & rebuild
  ${GREEN}pull${RESET}                                 Pull latest base images

${BOLD}Maintenance:${RESET}
  ${GREEN}clean${RESET}                                Remove dangling images/volumes
  ${GREEN}remove${RESET}     [target]                  Remove containers (keep data)
  ${GREEN}reset${RESET}                                ⚠️ Delete ALL data & containers

${BOLD}Development:${RESET}
  ${GREEN}shell${RESET}      [service]                 Open shell in container
  ${GREEN}exec${RESET}       [service] [command]       Execute command in container
  ${GREEN}logs${RESET}       [service]                 Stream logs
  ${GREEN}install${RESET}    [target]                  Install dependencies

${BOLD}Database:${RESET}
  ${GREEN}db-migrate${RESET}                           Run Alembic migrations
  ${GREEN}db-shell${RESET}                             Open PostgreSQL shell
  ${GREEN}backup${RESET}                               Create database backup

${BOLD}Testing:${RESET}
  ${GREEN}test${RESET}       [target]                  Run tests

${BOLD}Targets:${RESET} ${DIM}(optional, default: all)${RESET}
  backend    Backend services (api, workers, db, redis, traefik)
  frontend   Frontend service
  all        Everything ${DIM}(default)${RESET}

${BOLD}Flags:${RESET}
  --dev, -d      Development mode: backend containers + local Vite dev server
  --conda, -c    Use Conda instead of containers for backend

${BOLD}Examples:${RESET}
  ./manage.sh start                      # Production: all containers
  ./manage.sh start --dev                # Dev: backend containers + Vite
  ./manage.sh start backend --conda      # Backend via Conda
  ./manage.sh stop frontend              # Stop only frontend
  ./manage.sh build backend              # Build backend image only
  ./manage.sh shell backend              # Shell into backend container
  ./manage.sh exec backend python -v     # Run command in backend
  ./manage.sh logs backend -f            # Stream backend logs
  ./manage.sh db-migrate                 # Run migrations (auto-detect)
  ./manage.sh db-migrate --conda         # Run migrations via Conda
  ./manage.sh backup                     # Backup database
  ./manage.sh test                       # Run all tests (auto-detect)
  ./manage.sh test backend --conda       # Run backend tests via Conda
  ./manage.sh clean                      # Clean up dangling resources
  ./manage.sh update                     # Update all images

EOF
}

# ─── Main ──────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    case "$CMD" in
        help|--help|-h)
            print_help
            exit 0
            ;;
    esac

    case "$CMD" in
        start|stop|restart|build|update|pull|remove|clean|status|logs|reset|shell|exec|db-migrate|db-shell|backup)
            init_env
            detect_engine
            setup_podman_socket
            ;;
        install|test)
            if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
                init_env
                detect_engine
                setup_podman_socket
            fi
            ;;
    esac

    case "$CMD" in
        start)       cmd_start ;;
        stop)        cmd_stop ;;
        restart)     cmd_restart ;;
        build)       cmd_build ;;
        update)      cmd_update ;;
        pull)        cmd_pull ;;
        remove|rm)   cmd_remove ;;
        clean)       cmd_clean ;;
        shell)       cmd_shell ;;
        exec)        cmd_exec ;;
        status)      cmd_status ;;
        logs)        cmd_logs ;;
        install)     cmd_install ;;
        test)        cmd_test ;;
        db-migrate)  cmd_db_migrate ;;
        db-shell)    cmd_db_shell ;;
        backup)      cmd_backup ;;
        reset)       cmd_reset ;;
        *)           die "Unknown command: $CMD\nRun './manage.sh help' for usage." ;;
    esac
}

main "$@"
