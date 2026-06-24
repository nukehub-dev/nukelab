help_version() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./manage.sh version

Show the NukeLab version and detected container engine versions.

${BOLD}Examples:${RESET}
  ./manage.sh version
  ./manage.sh --version
EOF
}

cmd_version() {
    echo "${BOLD}NukeLab v2.0${RESET}"
    echo ""
    echo "Container engine: ${CONTAINER_ENGINE:-not detected}"
    if command -v "${CONTAINER_ENGINE:-podman}" >/dev/null 2>&1; then
        echo -n "  version: "
        "${CONTAINER_ENGINE:-podman}" --version 2>/dev/null | head -n 1
    fi
    echo "Compose command: ${COMPOSE:-not detected}"
    if [ -n "${COMPOSE:-}" ]; then
        echo -n "  version: "
        $COMPOSE version 2>/dev/null | head -n 1 || true
    fi
    echo "Project directory: $DIR"
}
