#!/bin/bash
set -e

echo "Starting NukeIDE..."

# Start Theia backend in background
cd /opt/nuke-ide
yarn start:browser &
THEIA_PID=$!

# Wait for Theia to be ready
echo "Waiting for Theia to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:3000 > /dev/null 2>&1; then
        echo "Theia is ready!"
        break
    fi
    sleep 1
done

# Start nginx in foreground
echo "Starting nginx..."
nginx -g 'daemon off;'
