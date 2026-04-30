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
# Globals set by parse_args()
CMD=""
TARGET=""
USE_DEV_MODE=false
USE_CONDA_MODE=false

parse_args() {
    CMD="${1:-help}"
    shift || true

    # Parse remaining args
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
            *)
                die "Unknown argument: $1\nRun './manage.sh help' for usage."
                ;;
        esac
        shift
    done

    # Defaults
    [[ -z "$TARGET" ]] && TARGET="all"
}

# ─── Environment ───────────────────────────────────────────────────────────
load_env_file() {
    local env_file="$1"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^#.*$ ]] && continue
        [[ -z "$line" ]] && continue
        export "$line" 2>/dev/null || true
    done < "$env_file"
}

init_env() {
    if [ -f .env ]; then
        log "Loading ${BOLD}.env${RESET}"
        load_env_file .env
    elif [ -f .env.development ]; then
        log "Loading ${BOLD}.env.development${RESET}"
        load_env_file .env.development
    else
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
    SOCK=$(podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null || true)
    if [ -n "$SOCK" ]; then
        export DOCKER_SOCKET="$SOCK"
    elif [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/podman/podman.sock" ]; then
        export DOCKER_SOCKET="$XDG_RUNTIME_DIR/podman/podman.sock"
    else
        export DOCKER_SOCKET="/run/podman/podman.sock"
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
    if $USE_CONDA_MODE; then
        # Conda mode: backend via conda, no containers
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

    if $USE_DEV_MODE; then
        # Dev mode: backend containers + local Vite
        step "Starting development stack..."
        
        # Stop frontend container if running (we use Vite dev server instead)
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
        # Production mode: everything in containers
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

cmd_logs() {
    local service="${TARGET:-}"
    [[ "$service" = "all" ]] && service=""
    $COMPOSE -f "$COMPOSE_FILE" logs -f ${service:-}
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

${BOLD}${MAGENTA}Commands:${RESET}
  ${GREEN}start${RESET}     [target] [--dev] [--conda]  Start services
  ${GREEN}stop${RESET}      [target]                    Stop services
  ${GREEN}restart${RESET}   [target] [--dev] [--conda]  Restart services
  ${GREEN}build${RESET}     [target]                    Build containers
  ${GREEN}status${RESET}                                Show status
  ${GREEN}logs${RESET}      [service]                   Stream logs
  ${GREEN}install${RESET}   [target]                    Install dependencies
  ${GREEN}reset${RESET}                                 Delete all data

${BOLD}Targets:${RESET} ${DIM}(optional, default: all)${RESET}
  backend    Backend services only
  frontend   Frontend only
  all        Everything ${DIM}(default)${RESET}what 

${BOLD}Flags:${RESET}
  --dev, -d      Development mode: containers + local Vite dev server
  --conda, -c    Use Conda instead of containers for backend

${BOLD}Examples:${RESET}
  ./manage.sh start                      # Production: all containers
  ./manage.sh start --dev                # Dev: backend containers + Vite
  ./manage.sh start backend --conda      # Backend via Conda, no containers
  ./manage.sh stop frontend              # Stop only frontend
  ./manage.sh build backend              # Build backend image only
  ./manage.sh restart                    # Restart everything
  ./manage.sh logs backend               # Stream backend logs
  ./manage.sh install                    # Install all deps
  ./manage.sh install frontend           # Install only frontend deps
  ./manage.sh status                     # Check what's running

EOF
}

# ─── Main ──────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    # Commands that don't need env/engine
    case "$CMD" in
        help|--help|-h)
            print_help
            exit 0
            ;;
    esac

    # Init env and engine for most commands
    case "$CMD" in
        start|stop|restart|build|status|logs|reset)
            init_env
            detect_engine
            setup_podman_socket
            ;;
        install)
            # Only init env if installing backend
            if [ "$TARGET" = "backend" ] || [ "$TARGET" = "all" ]; then
                init_env
            fi
            ;;
    esac

    # Dispatch
    case "$CMD" in
        start)      cmd_start ;;
        stop)       cmd_stop ;;
        restart)    cmd_restart ;;
        build)      cmd_build ;;
        status)     cmd_status ;;
        logs)       cmd_logs ;;
        install)    cmd_install ;;
        reset)      cmd_reset ;;
        *)          die "Unknown command: $CMD\nRun './manage.sh help' for usage." ;;
    esac
}

main "$@"
