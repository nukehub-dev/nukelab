#!/bin/bash

# Copyright (c) NukeLab Development Team.
# Distributed under the terms of the BSD-2-Clause License.

# Enable Shell exit on any error
set -e

# Store current directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Determine container engine
if command -v podman &> /dev/null; then
    CONTAINER_ENGINE=podman
elif command -v docker &> /dev/null; then
    CONTAINER_ENGINE=docker
else
    echo "Neither podman nor docker found. Please install one of them."
    exit 1
fi

# Determine compose command
if command -v podman-compose &> /dev/null; then
    COMPOSE_COMMAND="podman-compose -f compose.yml"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_COMMAND="docker-compose -f compose.yml"
elif command -v docker &> /dev/null && docker compose version &> /dev/null; then
    COMPOSE_COMMAND="docker compose -f compose.yml"
else
    echo "Neither podman-compose nor docker-compose found. Please install one of them."
    exit 1
fi

# Set the socket path
if [ "$CONTAINER_ENGINE" == "podman" ]; then
    # Get the socket path from podman
    SOCK_PATH=$(podman info --format '{{.Host.RemoteSocket.Path}}')
    export DOCKER_NUKELAB_HOST=$SOCK_PATH
else
    export DOCKER_NUKELAB_HOST=/var/run/docker.sock
fi

# Main script logic
case "$1" in
    build)
        cd $DIR/spawner
        echo "Building Spawner with ${CONTAINER_ENGINE}"

        # Add --format docker flag if using podman
        BUILD_ARGS=""
        if [ "$CONTAINER_ENGINE" == "podman" ]; then
            BUILD_ARGS="--format docker"
        fi
        ${CONTAINER_ENGINE} build ${BUILD_ARGS} -t nukelab-spawner .        
        cd $DIR
        ${COMPOSE_COMMAND} build
        ;;
    run)
        ${COMPOSE_COMMAND} up -d
        ;;
    *)
        echo "Usage: $0 {build|run}"
        exit 1
        ;;
esac