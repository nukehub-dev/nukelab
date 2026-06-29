#!/bin/bash
# Check that external base images in Dockerfiles are pinned by digest.
#
# Internal images (nukelab-*), build-arg references (FROM $BASE_IMAGE), and
# scratch are skipped. All other images must use the @sha256:<digest> form or
# this script reports them.
#
# Usage:
#   ./scripts/security/check-base-image-pinning.sh [--strict]
#
# Exit codes:
#   0  No unpinned external base images found (or not in strict mode).
#   1  Unpinned external base images found and --strict was passed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

STRICT=false

show_help() {
    cat << EOF
${0}: Check Dockerfile base image pinning.

Usage: ${0} [options]

Options:
  --strict    Return non-zero if any unpinned external base image is found
  -h, --help  Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict)
            STRICT=true
            shift
            ;;
        -h | --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

# Find Dockerfiles tracked by git, or fall back to a filesystem search.
mapfile -t dockerfiles < <(
    if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git -C "${REPO_ROOT}" ls-files --exclude-standard '*Dockerfile*'
    else
        find "${REPO_ROOT}" -type f -name 'Dockerfile*' -not -path '*/\.git/*' -not -path '*/node_modules/*' -not -path '*/\.venv*/*'
    fi | sort -u
)

if [[ ${#dockerfiles[@]} -eq 0 ]]; then
    echo "No Dockerfiles found."
    exit 0
fi

unpinned=0

for rel in "${dockerfiles[@]}"; do
    file="${REPO_ROOT}/${rel}"
    [[ -f "$file" ]] || continue

    declare -A stages=()
    line_no=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line_no=$((line_no + 1))

        # Only consider FROM lines.
        if [[ ! "$line" =~ ^[[:space:]]*FROM[[:space:]] ]]; then
            continue
        fi

        # Record any stage alias introduced by this FROM line so later
        # FROM references to it are not treated as external images.
        if [[ "$line" =~ [[:space:]]+[Aa][Ss][[:space:]]+([a-zA-Z0-9_-]+) ]]; then
            stages["${BASH_REMATCH[1]}"]=1
        fi

        # Strip leading whitespace, FROM keyword, and any --flag=... options.
        ref="${line#*FROM}"
        ref="${ref#*[[:space:]]}"
        # Remove --platform=... / --target=... style flags.
        while [[ "$ref" =~ ^--[a-zA-Z0-9_-]+=[^[:space:]]+[[:space:]]+ ]]; do
            ref="${ref#* }"
        done
        # Remove trailing AS <name> (case-insensitive).
        ref="$(printf '%s' "$ref" | sed -E 's/[[:space:]]+(AS|as)[[:space:]]+.*//')"
        # Trim whitespace.
        ref="${ref#${ref%%[![:space:]]*}}"
        ref="${ref%${ref##*[![:space:]]}}"

        # Skip internal / build-time / scratch references and multi-stage aliases.
        case "$ref" in
            "" | scratch | *\$* | nukelab-*)
                continue
                ;;
        esac
        if [[ -n "${stages[$ref]:-}" ]]; then
            continue
        fi

        # Pinned images contain a digest.
        if [[ "$ref" == *"@sha256:"* ]]; then
            continue
        fi

        echo "${rel}:${line_no}  unpinned base image: ${ref}"
        unpinned=$((unpinned + 1))
    done < "$file"
done

if [[ "$unpinned" -gt 0 ]]; then
    echo ""
    echo "Found ${unpinned} unpinned external base image(s)."
    if $STRICT; then
        echo "Pin images by digest (e.g., ubuntu:24.04@sha256:<digest>) or document exceptions." >&2
        exit 1
    fi
    exit 0
fi

echo "All external base images are pinned by digest or explicitly skipped."
exit 0
