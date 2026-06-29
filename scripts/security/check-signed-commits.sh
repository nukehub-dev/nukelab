#!/bin/bash
# Check that commits on the current branch are cryptographically signed.
#
# Usage:
#   ./scripts/security/check-signed-commits.sh [--strict]
#
# Exit codes:
#   0  All commits are signed (or not in strict mode).
#   1  Unsigned commits were found and --strict was passed.

set -euo pipefail

STRICT=false
SIGNED=0
UNSIGNED=0
MAX_DETAIL=10

show_help() {
    cat << EOF
${0}: Check commit signatures on the current branch.

Usage: ${0} [options]

Options:
  --strict    Return non-zero if any unsigned commit is found
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

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "Not inside a git repository; skipping signed-commit check."
    exit 0
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "Checking commit signatures on branch: ${BRANCH}"

# %G? status codes:
#   G = good (valid)
#   U = good but untrusted
#   B/X/Y/R = bad/expired/revoked
#   N = no signature
#   ? = unknown
while IFS=' ' read -r hash status; do
    case "$status" in
        G | U)
            SIGNED=$((SIGNED + 1))
            ;;
        "")
            # Empty status can occur for merges or unusual formats; treat as unsigned.
            UNSIGNED=$((UNSIGNED + 1))
            if [[ "$UNSIGNED" -le "$MAX_DETAIL" ]]; then
                echo "${hash}  unsigned (empty signature status)"
            fi
            ;;
        *)
            UNSIGNED=$((UNSIGNED + 1))
            if [[ "$UNSIGNED" -le "$MAX_DETAIL" ]]; then
                echo "${hash}  signature status: ${status}"
            fi
            ;;
    esac
done < <(git log "${BRANCH}" --format='%H %G?')

if [[ "$UNSIGNED" -gt "$MAX_DETAIL" ]]; then
    echo "... and $((UNSIGNED - MAX_DETAIL)) more unsigned commit(s)"
fi

echo ""
echo "Signed commits:   ${SIGNED}"
echo "Unsigned commits: ${UNSIGNED}"

if [[ "$UNSIGNED" -gt 0 ]]; then
    if $STRICT; then
        echo "Commits must be signed before merge. Configure commit signing and re-sign." >&2
        exit 1
    fi
    exit 0
fi

echo "All commits are signed."
exit 0
