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

help_clean() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl clean

Remove stopped containers, dangling images, dangling volumes, and build cache.

${BOLD}Examples:${RESET}
  ./nukelabctl clean
EOF
}

