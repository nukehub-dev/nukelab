#!/bin/bash
# SPDX-License-Identifier: BSD-2-Clause
#
# Add REUSE-style copyright and license headers to source files.
# Usage: ./scripts/add-license-headers.sh [--check]
#   --check    Exit with non-zero if any file is missing a header (CI mode).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_MODE=false
MISSING=0

COPYRIGHT_HOLDER="NukeHub Developers"
COPYRIGHT_YEARS="2023-2026"

if [[ "${1:-}" == "--check" ]]; then
    CHECK_MODE=true
fi

# Insert a header block after an optional shebang line.
# For files without a shebang the header is prepended at the top.
insert_after_shebang() {
    local file="$1"
    local header="$2"

    local first_line
    first_line=$(head -n 1 "$file")

    local tmp
    tmp=$(mktemp)

    if [[ "$first_line" == '#!'* ]]; then
        printf '%s\n' "$first_line" > "$tmp"
        printf '%s\n\n' "$header" >> "$tmp"
        tail -n +2 "$file" >> "$tmp"
    else
        printf '%s\n\n' "$header" > "$tmp"
        cat "$file" >> "$tmp"
    fi

    mv "$tmp" "$file"
}

# Ensure a file has both REUSE lines. If it already has a license line but no
# copyright line, the copyright line is inserted before the license line.
ensure_reuse_header() {
    local file="$1"
    local prefix="$2"

    if grep -q "SPDX-FileCopyrightText" "$file"; then
        return 0
    fi

    if $CHECK_MODE; then
        echo "Missing REUSE copyright header: $file"
        return 1
    fi

    local copyright_line="${prefix} SPDX-FileCopyrightText: ${COPYRIGHT_YEARS} ${COPYRIGHT_HOLDER}"
    local license_line="${prefix} SPDX-License-Identifier: BSD-2-Clause"

    if grep -q "SPDX-License-Identifier" "$file"; then
        local tmp
        tmp=$(mktemp)
        awk -v cp="$prefix" \
            -v copy="SPDX-FileCopyrightText: ${COPYRIGHT_YEARS} ${COPYRIGHT_HOLDER}" \
            -v lic="SPDX-License-Identifier: BSD-2-Clause" '
            !done && $0 ~ "^" cp " " lic {
                print cp " " copy
                print cp " " lic
                done = 1
                next
            }
            { print }
        ' "$file" > "$tmp"
        mv "$tmp" "$file"
        echo "Added REUSE copyright header: $file"
    else
        insert_after_shebang "$file" "${copyright_line}"$'\n'"${license_line}"
        echo "Added REUSE header: $file"
    fi
}

process_files() {
    local pattern="$1"
    local prefix="$2"
    shift 2
    local dirs=("$@")

    local dir
    for dir in "${dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
            continue
        fi

        local file
        while IFS= read -r -d '' file; do
            # Skip generated artifacts and runtime state files.
            case "$file" in
                */routeTree.gen.ts) continue ;;
                */.nukelab-state*.sh) continue ;;
            esac

            if ! ensure_reuse_header "$file" "$prefix"; then
                MISSING=$((MISSING + 1))
            fi
        done < <(find "$dir" \
            -type d \( \
                -name '.venv' -o \
                -name '.venv-dev' -o \
                -name 'node_modules' -o \
                -name '__pycache__' -o \
                -name '.git' -o \
                -name 'dist' -o \
                -name 'build' -o \
                -name 'test-results' \
            \) -prune -o \
            -type f -name "$pattern" -print0)
    done
}

process_files "*.py" "#" "$ROOT_DIR/backend"
process_files "*.ts" "//" "$ROOT_DIR/frontend/src"
process_files "*.tsx" "//" "$ROOT_DIR/frontend/src"
process_files "*.go" "//" "$ROOT_DIR/services/auth-sidecar"
process_files "*.sh" "#" "$ROOT_DIR/scripts" "$ROOT_DIR/environments" "$ROOT_DIR/backend/tests/scripts"

# The top-level dispatcher has no .sh extension.
if [[ -f "$ROOT_DIR/nukelabctl" ]]; then
    ensure_reuse_header "$ROOT_DIR/nukelabctl" "#" || true
fi

if $CHECK_MODE && [ "$MISSING" -gt 0 ]; then
    echo "Found $MISSING file(s) missing license headers."
    exit 1
fi

if $CHECK_MODE; then
    echo "All source files have REUSE headers."
else
    echo "REUSE headers added where missing."
fi
