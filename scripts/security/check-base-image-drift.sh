#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Review external Dockerfile base images for tag/digest drift.
#
# The script parses tracked Dockerfiles for pinned external references of the
# form image:tag@sha256:<digest> and resolves the tag's current digest without
# pulling image layers. It skips the same references as the strict pinning
# check: scratch, build-arg references, internal nukelab images, and stage
# aliases. Digest-only references (image@sha256:<digest>) are skipped because
# they have no tag to drift.
#
# The pinned digest may be a multi-arch index digest or one platform manifest
# digest, so a reference is current when it matches either the tag's index
# digest or the selected platform manifest digest.
#
# Usage:
#   ./scripts/security/check-base-image-drift.sh [options]
#
# Options:
#   --platform <os/arch[/variant]>  Platform manifest to compare (default:
#                                   linux/amd64)
#   --output <path>                 Also write the report to this path
#   -h, --help                      Show this help message
#
# Environment:
#   NUKELAB_BASE_IMAGE_DRIFT_TIMEOUT_SECONDS  Per-resolution timeout (30)
#   NUKELAB_BASE_IMAGE_DRIFT_MAX_IMAGES       Unique tag resolution cap (64)
#   NUKELAB_BASE_IMAGE_DRIFT_MAX_SECONDS      Total resolution budget (300)
#
# Exit codes:
#   0  No drift found.
#   1  Drift found (the report may also list resolution errors).
#   2  Resolution or configuration failure (no drift rows are known).
#
# Registry credentials are whatever the Docker/Buildx config already provides
# (for example an optional `docker login`); this script never reads, writes, or
# prints them. Registry stderr is classified into a bounded reason code instead
# of being echoed, so auth headers and tokens cannot leak.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PLATFORM="linux/amd64"
OUTPUT_PATH=""
RETRY_ATTEMPTS=3
RESOLVE_TIMEOUT_SECONDS="${NUKELAB_BASE_IMAGE_DRIFT_TIMEOUT_SECONDS:-30}"
MAX_UNIQUE_IMAGES="${NUKELAB_BASE_IMAGE_DRIFT_MAX_IMAGES:-64}"
MAX_TOTAL_SECONDS="${NUKELAB_BASE_IMAGE_DRIFT_MAX_SECONDS:-300}"
MAX_ROWS=200
MAX_DETAILS=400

show_help() {
    cat << EOF
${0}: Review Dockerfile base-image tag/digest drift.

Usage: ${0} [options]

Options:
  --platform <os/arch[/variant]>  Platform manifest to compare (default: linux/amd64)
  --output <path>                 Also write the report to this path
  -h, --help                      Show this help message

Exit codes:
  0  No drift found.
  1  Drift found.
  2  Resolution or configuration failure.
EOF
}

die_usage() {
    echo "Error: $*" >&2
    show_help >&2
    exit 2
}

die_config() {
    echo "Error: $*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform)
            [[ $# -ge 2 ]] || die_usage "--platform requires a value"
            PLATFORM="$2"
            shift 2
            ;;
        --platform=*)
            PLATFORM="${1#*=}"
            shift
            ;;
        --output)
            [[ $# -ge 2 ]] || die_usage "--output requires a path"
            OUTPUT_PATH="$2"
            shift 2
            ;;
        --output=*)
            OUTPUT_PATH="${1#*=}"
            shift
            ;;
        -h | --help)
            show_help
            exit 0
            ;;
        *)
            die_usage "unknown option: $1"
            ;;
    esac
done

if [[ ! "$PLATFORM" =~ ^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?$ ]]; then
    die_usage "invalid platform '${PLATFORM}' (expected <os>/<architecture>[/<variant>])"
fi
IFS='/' read -r PLATFORM_OS PLATFORM_ARCH PLATFORM_VARIANT <<< "$PLATFORM"
PLATFORM_VARIANT="${PLATFORM_VARIANT:-}"

for value in "$RESOLVE_TIMEOUT_SECONDS" "$MAX_UNIQUE_IMAGES" "$MAX_TOTAL_SECONDS"; do
    [[ "$value" =~ ^[0-9]+$ ]] || die_config "time and image limits must be positive integers"
done
if ((RESOLVE_TIMEOUT_SECONDS < 1 || MAX_UNIQUE_IMAGES < 1 || MAX_TOTAL_SECONDS < 1)); then
    die_config "time and image limits must be positive integers"
fi

for tool in docker jq sha256sum timeout; do
    command -v "$tool" > /dev/null 2>&1 || die_config "required tool not found: ${tool}"
done

if ! docker buildx version > /dev/null 2>&1; then
    die_config "docker buildx is required to resolve registry manifests"
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nukelab-base-image-drift.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

ROWS_FILE="${TMP_DIR}/rows"
DETAILS_FILE="${TMP_DIR}/details"
REPORT_FILE="${TMP_DIR}/report"
: > "$ROWS_FILE"
: > "$DETAILS_FILE"

declare -A CACHE_STATE=()
declare -A CACHE_INDEX_DIGEST=()
declare -A CACHE_PLATFORM_DIGEST=()
declare -A CACHE_ERROR=()

checked=0
drifted=0
current_count=0
resolution_errors=0
unique_resolved=0
rows_truncated=0
skipped_scratch=0
skipped_build_arg=0
skipped_internal=0
skipped_stage=0
skipped_digest_only=0
skipped_unpinned=0
skipped_malformed=0
start_seconds=$SECONDS

_classify_error() {
    local err_file="$1"

    if grep -Eqi '429|too many requests|rate limit' "$err_file" 2> /dev/null; then
        echo "rate-limited"
    elif grep -Eqi 'timeout|timed out|deadline exceeded' "$err_file" 2> /dev/null; then
        echo "timeout"
    elif grep -Eqi '401|unauthorized|authentication required' "$err_file" 2> /dev/null; then
        echo "auth-required"
    elif grep -Eqi '403|denied|forbidden' "$err_file" 2> /dev/null; then
        echo "access-denied"
    elif grep -Eqi '404|not found|manifest unknown' "$err_file" 2> /dev/null; then
        echo "not-found"
    elif grep -Eqi 'no such host|connection refused|network is unreachable|tls|dial tcp' "$err_file" 2> /dev/null; then
        echo "network-error"
    else
        echo "registry-error"
    fi
}

# Print the selected platform manifest digest from an index, or nothing when
# the requested platform is absent.
_select_platform_digest() {
    local raw_file="$1"
    local digest
    local variant
    local first=""
    local exact=""

    while IFS=$'\t' read -r digest variant; do
        [[ -n "$digest" ]] || continue
        [[ -n "$first" ]] || first="$digest"
        if [[ -n "$PLATFORM_VARIANT" ]]; then
            if [[ "$variant" == "$PLATFORM_VARIANT" ]]; then
                exact="$digest"
                break
            fi
        elif [[ -z "$variant" || "$variant" == "-" ]]; then
            exact="$digest"
            break
        fi
    done < <(
        jq -r \
            --arg os "$PLATFORM_OS" \
            --arg arch "$PLATFORM_ARCH" \
            '
            [ .manifests[]
              | select((.platform.os // "") == $os and (.platform.architecture // "") == $arch)
              | {digest: .digest, variant: (.platform.variant // "")} ]
            | sort_by(.digest)
            | .[]
            | [.digest, .variant]
            | @tsv
            ' "$raw_file"
    )

    printf '%s\n' "${exact:-$first}"
}

_resolve_image() {
    local image_ref="$1"
    local key_hash
    local raw_file
    local err_file
    local attempt
    local rc
    local current_digest
    local platform_digest
    local classification

    if [[ -n "${CACHE_STATE[$image_ref]:-}" ]]; then
        return 0
    fi

    if ((unique_resolved >= MAX_UNIQUE_IMAGES)); then
        CACHE_STATE["$image_ref"]="error"
        CACHE_ERROR["$image_ref"]="image-budget-exhausted"
        resolution_errors=$((resolution_errors + 1))
        printf 'resolved %s resolution=error reason=image-budget-exhausted\n' "$image_ref" >> "$DETAILS_FILE"
        return 0
    fi
    unique_resolved=$((unique_resolved + 1))

    key_hash="$(printf '%s' "$image_ref" | sha256sum | cut -d ' ' -f1)"
    raw_file="${TMP_DIR}/manifest-${key_hash}.json"
    err_file="${TMP_DIR}/manifest-${key_hash}.err"
    attempt=1

    while ((attempt <= RETRY_ATTEMPTS)); do
        if ((SECONDS - start_seconds > MAX_TOTAL_SECONDS)); then
            classification="time-budget-exhausted"
            break
        fi

        rc=0
        timeout "$RESOLVE_TIMEOUT_SECONDS" \
            docker buildx imagetools inspect "$image_ref" --raw > "$raw_file" 2> "$err_file" || rc=$?

        if ((rc == 0)); then
            if [[ ! -s "$raw_file" ]] || ! jq -e . "$raw_file" > /dev/null 2>&1; then
                classification="invalid-manifest-response"
            else
                current_digest="sha256:$(sha256sum "$raw_file" | cut -d ' ' -f1)"
                platform_digest="$current_digest"
                if jq -e '(.manifests | type) == "array" and (.manifests | length) > 0' "$raw_file" > /dev/null 2>&1; then
                    platform_digest="$(_select_platform_digest "$raw_file")"
                fi
                if [[ -z "$platform_digest" ]]; then
                    classification="platform-unavailable"
                else
                    CACHE_STATE["$image_ref"]="ok"
                    CACHE_INDEX_DIGEST["$image_ref"]="$current_digest"
                    CACHE_PLATFORM_DIGEST["$image_ref"]="$platform_digest"
                    if [[ "$current_digest" == "$platform_digest" ]]; then
                        printf 'resolved %s resolution=ok digest=%s\n' "$image_ref" "$current_digest" >> "$DETAILS_FILE"
                    else
                        printf 'resolved %s resolution=ok index=%s platform=%s\n' \
                            "$image_ref" "$current_digest" "$platform_digest" >> "$DETAILS_FILE"
                    fi
                    rm -f "$raw_file" "$err_file"
                    return 0
                fi
            fi
        elif ((rc == 124)); then
            classification="timeout"
        else
            classification="$(_classify_error "$err_file")"
        fi

        if ((attempt < RETRY_ATTEMPTS)) \
            && [[ "$classification" == "rate-limited" || "$classification" == "timeout" || "$classification" == "network-error" ]]; then
            sleep $((attempt * 2))
            attempt=$((attempt + 1))
            continue
        fi
        break
    done

    rm -f "$raw_file" "$err_file"
    CACHE_STATE["$image_ref"]="error"
    CACHE_ERROR["$image_ref"]="$classification"
    resolution_errors=$((resolution_errors + 1))
    printf 'resolved %s resolution=error reason=%s\n' "$image_ref" "$classification" >> "$DETAILS_FILE"
}

# Find Dockerfiles tracked by git, or fall back to a filesystem search, using
# the same discovery convention as check-base-image-pinning.sh.
mapfile -t dockerfiles < <(
    if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git -C "$REPO_ROOT" ls-files --exclude-standard '*Dockerfile*'
    else
        (cd "$REPO_ROOT" && find . -type f -name 'Dockerfile*' -not -path '*/\.git/*' -not -path '*/node_modules/*' -not -path '*/\.venv*/*') | sed 's|^\./||'
    fi | sort -u
)

for rel in "${dockerfiles[@]}"; do
    file="${REPO_ROOT}/${rel}"
    [[ -f "$file" ]] || continue

    declare -A stages=()
    line_no=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line_no=$((line_no + 1))

        if [[ ! "$line" =~ ^[[:space:]]*[Ff][Rr][Oo][Mm][[:space:]]+(.*)$ ]]; then
            continue
        fi
        ref="${BASH_REMATCH[1]}"

        # Record any stage alias introduced by this FROM line before parsing
        # the reference, so a later FROM <alias> is not treated as external.
        if [[ "$line" =~ [[:space:]]+[Aa][Ss][[:space:]]+([A-Za-z0-9_.-]+)[[:space:]]*$ ]]; then
            stages["${BASH_REMATCH[1],,}"]=1
        fi

        # Remove --platform=... / --target=... style options.
        while [[ "$ref" =~ ^--[A-Za-z0-9_-]+=[^[:space:]]+[[:space:]]+(.*)$ ]]; do
            ref="${BASH_REMATCH[1]}"
        done
        # Remove trailing AS <name> (case-insensitive).
        if [[ "$ref" =~ ^(.*[^[:space:]])[[:space:]]+[Aa][Ss][[:space:]]+[A-Za-z0-9_.-]+[[:space:]]*$ ]]; then
            ref="${BASH_REMATCH[1]}"
        fi
        # Trim leading and trailing whitespace.
        ref="${ref#"${ref%%[![:space:]]*}"}"
        ref="${ref%"${ref##*[![:space:]]}"}"

        case "$ref" in
            "")
                continue
                ;;
            scratch)
                skipped_scratch=$((skipped_scratch + 1))
                continue
                ;;
            *'$'*)
                skipped_build_arg=$((skipped_build_arg + 1))
                continue
                ;;
            nukelab-* | */nukelab-*)
                skipped_internal=$((skipped_internal + 1))
                continue
                ;;
        esac

        if [[ -n "${stages[${ref,,}]:-}" ]]; then
            skipped_stage=$((skipped_stage + 1))
            continue
        fi

        if [[ "$ref" != *"@sha256:"* ]]; then
            skipped_unpinned=$((skipped_unpinned + 1))
            continue
        fi

        pinned="${ref##*@}"
        image_ref="${ref%@*}"
        pinned="${pinned,,}"
        if [[ ! "$pinned" =~ ^sha256:[0-9a-f]{64}$ ]]; then
            skipped_malformed=$((skipped_malformed + 1))
            continue
        fi

        last_segment="${image_ref##*/}"
        if [[ "$last_segment" != *:* ]]; then
            skipped_digest_only=$((skipped_digest_only + 1))
            continue
        fi
        tag="${last_segment##*:}"
        if [[ -z "$tag" ]]; then
            skipped_malformed=$((skipped_malformed + 1))
            continue
        fi

        checked=$((checked + 1))
        _resolve_image "$image_ref"

        state="${CACHE_STATE[$image_ref]}"
        if [[ "$state" != "ok" ]]; then
            printf 'detail %s:%d %s status=error reason=%s\n' \
                "$rel" "$line_no" "$image_ref" "${CACHE_ERROR[$image_ref]}" >> "$DETAILS_FILE"
            continue
        fi

        index_digest="${CACHE_INDEX_DIGEST[$image_ref]}"
        platform_digest="${CACHE_PLATFORM_DIGEST[$image_ref]}"

        if [[ "$pinned" == "$index_digest" || "$pinned" == "$platform_digest" ]]; then
            current_count=$((current_count + 1))
            continue
        fi

        drifted=$((drifted + 1))
        if ((drifted <= MAX_ROWS)); then
            printf '%s:%d %s %s %s\n' \
                "$rel" "$line_no" "$image_ref" "$pinned" "$index_digest" >> "$ROWS_FILE"
            printf 'detail %s:%d %s status=drift index=%s platform=%s\n' \
                "$rel" "$line_no" "$image_ref" "$index_digest" "$platform_digest" >> "$DETAILS_FILE"
        else
            rows_truncated=1
        fi
    done < "$file"
done

detail_total=0
if [[ -s "$DETAILS_FILE" ]]; then
    detail_total="$(sort -u "$DETAILS_FILE" | wc -l)"
fi
if ((detail_total > MAX_DETAILS)); then
    rows_truncated=1
fi

{
    echo "base-image-digest-drift/v1"
    echo "platform=${PLATFORM}"
    echo "drift:"
    if [[ -s "$ROWS_FILE" ]]; then
        sort -t: -k1,1 -k2,2n "$ROWS_FILE"
    else
        echo "(none)"
    fi
    echo "summary checked=${checked} drifted=${drifted} current=${current_count} resolution_errors=${resolution_errors} unique_images=${unique_resolved} skipped_scratch=${skipped_scratch} skipped_build_arg=${skipped_build_arg} skipped_internal=${skipped_internal} skipped_stage=${skipped_stage} skipped_digest_only=${skipped_digest_only} skipped_unpinned=${skipped_unpinned} skipped_malformed=${skipped_malformed} rows_truncated=${rows_truncated}"
    echo "details:"
    if [[ -s "$DETAILS_FILE" ]]; then
        sort -u "$DETAILS_FILE" | awk -v max="$MAX_DETAILS" 'NR <= max'
    else
        echo "(none)"
    fi
} > "$REPORT_FILE"

cat "$REPORT_FILE"

if [[ -n "$OUTPUT_PATH" ]]; then
    if ! mkdir -p "$(dirname "$OUTPUT_PATH")" || ! cp "$REPORT_FILE" "$OUTPUT_PATH"; then
        die_config "cannot write report to ${OUTPUT_PATH}"
    fi
fi

if ((drifted > 0)); then
    exit 1
fi
if ((resolution_errors > 0 || rows_truncated > 0)); then
    exit 2
fi
exit 0
