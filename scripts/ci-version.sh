#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Generate Docker image tags for CI based on git ref and SHA.
#
# Reads:
#   GITHUB_REF  - e.g. refs/heads/main, refs/tags/v1.2.3, refs/pull/42/merge
#   GITHUB_SHA  - full commit SHA
#   IMAGE_NAME  - optional image name to prefix tags, e.g.
#                 ghcr.io/owner/nukelab-backend. When set, the tags output
#                 contains full image references and a "latest" tag is added
#                 automatically for refs that request it.
#
# Writes GitHub Actions step outputs:
#   tags    - newline-separated list of image tags. With IMAGE_NAME set these
#             are full references (e.g. ghcr.io/owner/repo:main); otherwise
#             they are bare tag suffixes.
#   version - primary version identifier
#   latest  - "true" if the "latest" tag should also be applied
#
# Usage in a workflow:
#   - run: ./scripts/ci-version.sh
#     env:
#       GITHUB_REF: ${{ github.ref }}
#       GITHUB_SHA: ${{ github.sha }}
#       IMAGE_NAME: ghcr.io/${{ github.repository_owner }}/nukelab-backend

set -euo pipefail

_ref="${GITHUB_REF:-refs/heads/main}"
_sha="${GITHUB_SHA:-$(git rev-parse HEAD 2> /dev/null || echo unknown)}"
_short_sha="${_sha:0:7}"
_image="${IMAGE_NAME:-}"

_tags=()
_version=""
_latest="false"

case "$_ref" in
    refs/tags/v*.*.*)
        _version="${_ref#refs/tags/v}"
        _tags+=("$_version")
        _tags+=("sha-$_short_sha")
        _latest="true"
        ;;
    refs/heads/main)
        _version="main"
        _tags+=("$_version")
        _tags+=("sha-$_short_sha")
        _latest="true"
        ;;
    refs/heads/*)
        _version="${_ref#refs/heads/}"
        # Sanitize branch name so it is a valid Docker tag
        _version="${_version//[^a-zA-Z0-9_.-]/-}"
        _tags+=("$_version")
        _tags+=("sha-$_short_sha")
        ;;
    refs/pull/*/merge)
        _pr="${_ref#refs/pull/}"
        _pr="${_pr%/merge}"
        _version="pr-$_pr"
        _tags+=("$_version")
        _tags+=("sha-$_short_sha")
        ;;
    *)
        _version="sha-$_short_sha"
        _tags+=("$_version")
        ;;
esac

# Add the floating "latest" tag when requested and an image name is provided.
if [ "$_latest" = "true" ] && [ -n "$_image" ]; then
    _tags+=("latest")
fi

# Prefix with image name when provided, otherwise leave tags as bare suffixes.
if [ -n "$_image" ]; then
    _prefixed_tags=()
    for _tag in "${_tags[@]}"; do
        _prefixed_tags+=("${_image}:${_tag}")
    done
    _tags=("${_prefixed_tags[@]}")
fi

# GitHub Actions: write outputs
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        printf 'tags<<EOF\n'
        printf '%s\n' "${_tags[@]}"
        printf 'EOF\n'
        printf 'version=%s\n' "$_version"
        printf 'latest=%s\n' "$_latest"
    } >> "$GITHUB_OUTPUT"
fi

# Human-readable summary for logs
echo "Version: $_version"
echo "Latest: $_latest"
echo "Tags: ${_tags[*]}"
