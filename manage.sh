#!/bin/bash

# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause License.

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Detect container engine
if command -v podman &> /dev/null; then
    CONTAINER_ENGINE=podman
    echo "Using Podman as container engine"
elif command -v docker &> /dev/null; then
    CONTAINER_ENGINE=docker
    echo "Using Docker as container engine"
else
    echo "ERROR: Neither podman nor docker found. Please install one of them."
    exit 1
fi

# Detect compose command
if command -v podman-compose &> /dev/null; then
    COMPOSE_COMMAND="podman-compose"
    echo "Using podman-compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_COMMAND="docker-compose"
    echo "Using docker-compose"
elif $CONTAINER_ENGINE compose version &> /dev/null; then
    COMPOSE_COMMAND="$CONTAINER_ENGINE compose"
    echo "Using $CONTAINER_ENGINE compose"
else
    echo "ERROR: No compose command found. Please install docker-compose or podman-compose."
    exit 1
fi

# Set socket path for Podman
if [ "$CONTAINER_ENGINE" == "podman" ]; then
    # Try to get socket from podman info (works for both rootless and rootful)
    SOCK_PATH=$(podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null || echo "")
    
    if [ -n "$SOCK_PATH" ]; then
        export DOCKER_SOCKET="$SOCK_PATH"
        echo "Podman socket (from podman info): $SOCK_PATH"
    elif [ -n "$XDG_RUNTIME_DIR" ] && [ -S "$XDG_RUNTIME_DIR/podman/podman.sock" ]; then
        # Rootless podman (default for non-root users)
        export DOCKER_SOCKET="$XDG_RUNTIME_DIR/podman/podman.sock"
        echo "Podman socket (rootless): $DOCKER_SOCKET"
    elif [ -S "/run/podman/podman.sock" ]; then
        # Rootful podman (running as root)
        export DOCKER_SOCKET="/run/podman/podman.sock"
        echo "Podman socket (rootful): $DOCKER_SOCKET"
    else
        # Fallback - use XDG_RUNTIME_DIR if available
        if [ -n "$XDG_RUNTIME_DIR" ]; then
            export DOCKER_SOCKET="$XDG_RUNTIME_DIR/podman/podman.sock"
        else
            export DOCKER_SOCKET="/run/podman/podman.sock"
        fi
        echo "WARNING: Podman socket not found, using fallback: $DOCKER_SOCKET"
        echo "Make sure Podman is running: podman machine start (macOS/Win) or systemctl --user start podman.socket (Linux)"
    fi
    export DOCKER_NUKELAB_HOST="$DOCKER_SOCKET"
else
    export DOCKER_SOCKET="/var/run/docker.sock"
fi

# Conda check
if command -v conda &> /dev/null; then
    echo "Conda detected: $(conda --version)"
fi

# Functions
start() {
    echo "Starting NukeLab services..."
    $COMPOSE_COMMAND -f docker-compose.yml up -d
    echo "Services started!"
    echo "  Frontend: http://localhost"
    echo "  API: http://localhost/api"
    echo "  Traefik Dashboard: http://localhost:8080"
}

stop() {
    echo "Stopping NukeLab services..."
    $COMPOSE_COMMAND -f docker-compose.yml down
}

restart() {
    stop
    start
}

build() {
    echo "Building NukeLab services..."
    $COMPOSE_COMMAND -f docker-compose.yml build
}

logs() {
    $COMPOSE_COMMAND -f docker-compose.yml logs -f "$@"
}

status() {
    $COMPOSE_COMMAND -f docker-compose.yml ps
}

conda_setup() {
    if ! command -v conda &> /dev/null; then
        echo "ERROR: Conda not found. Please install Anaconda or Miniconda."
        exit 1
    fi
    
    echo "Setting up Conda environment for backend..."
    cd backend
    
    if conda env list | grep -q "nukelab-backend"; then
        echo "Environment 'nukelab-backend' already exists. Updating..."
        conda env update -f environment.yml --prune
    else
        echo "Creating Conda environment 'nukelab-backend'..."
        conda env create -f environment.yml
    fi
    
    echo "Conda environment ready!"
    echo "Activate with: conda activate nukelab-backend"
}

conda_run() {
    if ! command -v conda &> /dev/null; then
        echo "ERROR: Conda not found."
        exit 1
    fi
    
    if ! conda env list | grep -q "nukelab-backend"; then
        echo "Conda environment not found. Run './manage.sh conda-setup' first."
        exit 1
    fi
    
    echo "Starting backend with Conda environment..."
    cd backend
    conda activate nukelab-backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
}

help() {
    cat << EOF
NukeLab Platform v2.0 - Management Script

Usage: ./manage.sh [command]

Container Commands:
  start        Start all services (detached)
  stop         Stop all services
  restart      Restart all services
  build        Build/rebuild all containers
  logs         Show logs (use: ./manage.sh logs [service])
  status       Show running containers

Conda Commands:
  conda-setup  Create/update Conda environment for backend
  conda-run    Run backend using Conda (for local development)

Examples:
  ./manage.sh start
  ./manage.sh logs backend
  ./manage.sh conda-setup

EOF
}

# Main
case "${1:-help}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    build)
        build
        ;;
    logs)
        shift
        logs "$@"
        ;;
    status)
        status
        ;;
    conda-setup)
        conda_setup
        ;;
    conda-run)
        conda_run
        ;;
    help|--help|-h)
        help
        ;;
    *)
        echo "Unknown command: $1"
        help
        exit 1
        ;;
esac
