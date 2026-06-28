#!/bin/bash
help_version() {
    cat <<-EOF
${BOLD}Usage:${RESET} ./nukelabctl version

Show the NukeLab version and detected container engine versions.

${BOLD}Examples:${RESET}
  ./nukelabctl version
  ./nukelabctl --version
EOF
}

# Resolve the NukeLab version string. Preference order:
#   1. $DIR/VERSION file (publishable artifact)
#   2. git describe --tags (e.g. v2.0, v2.0-3-gabc123)
#   3. hardcoded default (kept as a last-resort fallback)
_nukelab_version() {
    local version
    if [ -f "$DIR/VERSION" ]; then
        version=$(tr -d '[:space:]' < "$DIR/VERSION" 2>/dev/null || true)
        if [ -n "$version" ]; then
            echo "$version"
            return
        fi
    fi
    if command -v git >/dev/null 2>&1 && [ -d "$DIR/.git" ]; then
        # --tags only succeeds when at least one tag exists; --always is
        # intentionally omitted so a bare short-sha never masks the
        # hardcoded fallback default. The trailing `|| true` plus the `if`
        # guard both neutralize the ERR trap inherited via `set -E` so a
        # tag-less repo falls through to the v2.0 default instead of aborting.
        if version=$(cd "$DIR" && git describe --tags 2>/dev/null || true); then
            if [ -n "$version" ]; then
                echo "$version"
                return
            fi
        fi
    fi
    echo "v2.0"
}

cmd_version() {
    echo "${BOLD}NukeLab $(_nukelab_version)${RESET}"
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
