#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Check that commits are cryptographically signed.
#
# Usage:
#   ./scripts/security/check-signed-commits.sh [--strict] [--range <base>..<head>]
#
# Without --range, every commit reachable from the current branch is checked.
# With --range, exactly the commits in <base>..<head> are checked. An empty
# range is not a signature failure.
#
# Exit codes:
#   0  All checked commits are signed, the range is empty, or --strict was
#      not passed.
#   1  Unsigned commits were found with --strict, or the arguments or range
#      are invalid.

set -euo pipefail

STRICT=false
RANGE=""
RANGE_BASE=""
RANGE_HEAD=""
SIGNED=0
UNSIGNED=0
MAX_DETAIL=10

show_help() {
    cat << EOF
${0}: Check commit signatures.

Usage: ${0} [options]

Options:
  --range <base>..<head>  Check only commits in the given range
  --strict                Return non-zero if any unsigned commit is found
  -h, --help              Show this help message

Without --range, all commits reachable from the current branch are checked.
EOF
}

_validate_range() {
    local range="$1"
    local base head remainder

    if [[ -z "$range" || "$range" == -* || "$range" == *[[:space:]]* ]]; then
        return 1
    fi
    if [[ "$range" != *..* || "$range" == *...* ]]; then
        return 1
    fi

    remainder="${range#*..}"
    # A second ".." means this is not a single two-dot range.
    if [[ "$remainder" == *..* ]]; then
        return 1
    fi

    base="${range%%..*}"
    head="$remainder"
    if [[ -z "$base" || -z "$head" ]]; then
        return 1
    fi

    RANGE_BASE="$base"
    RANGE_HEAD="$head"
    return 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict)
            STRICT=true
            shift
            ;;
        --range)
            if [[ $# -lt 2 ]]; then
                echo "--range requires a <base>..<head> value" >&2
                show_help
                exit 1
            fi
            RANGE="$2"
            if ! _validate_range "$RANGE"; then
                echo "Invalid range: '${RANGE}' (expected <base>..<head>)" >&2
                show_help
                exit 1
            fi
            shift 2
            ;;
        --range=*)
            RANGE="${1#*=}"
            if ! _validate_range "$RANGE"; then
                echo "Invalid range: '${RANGE}' (expected <base>..<head>)" >&2
                show_help
                exit 1
            fi
            shift
            ;;
        -h | --help)
            show_help
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            show_help
            exit 1
            ;;
        *)
            echo "Unexpected argument: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "Not inside a git repository; skipping signed-commit check."
    exit 0
fi

if [[ -n "$RANGE" ]]; then
    echo "Checking commit signatures in range: ${RANGE}"
    if ! git rev-parse --verify --quiet "${RANGE_BASE}^{commit}" > /dev/null 2>&1; then
        echo "Invalid range '${RANGE}': base '${RANGE_BASE}' does not resolve to a commit." >&2
        exit 1
    fi
    if ! git rev-parse --verify --quiet "${RANGE_HEAD}^{commit}" > /dev/null 2>&1; then
        echo "Invalid range '${RANGE}': head '${RANGE_HEAD}' does not resolve to a commit." >&2
        exit 1
    fi
    REVISION="$RANGE"
else
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    echo "Checking commit signatures on branch: ${BRANCH}"
    REVISION="$BRANCH"
fi

if ! LOG_OUTPUT="$(git log "$REVISION" --format='%H %G?')"; then
    echo "Failed to list commits for '${REVISION}'." >&2
    exit 1
fi

if [[ -z "$LOG_OUTPUT" ]]; then
    if [[ -n "$RANGE" ]]; then
        echo "No commits in range ${RANGE}; nothing to check."
    else
        echo "No commits to check on branch: ${BRANCH}"
    fi
    exit 0
fi

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
done <<< "$LOG_OUTPUT"

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
