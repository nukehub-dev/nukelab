#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Bump the NukeLab platform version across all version-bearing files.
#
# The git tag (vX.Y.Z) is the release source of truth; this script syncs
# every checked-in copy of the version so a release is one command:
#
#   scripts/bump-version.sh 2.1.0
#
# Updates:
#   VERSION                  - CLI/publish artifact read by _nukelab_version
#   frontend/package.json    - frontend package version (via npm, which also
#   frontend/package-lock.json keeps the lockfile in sync)
#   CHANGELOG.md             - stamps [Unreleased] with the new version + date
#
# Deliberately NOT updated: backend/app/version.py. The backend reports its
# version dynamically (APP_VERSION build arg injected by CI); version.py is a
# fixed "0.0.0-dev" fallback for local builds and is never bumped.
#
# The script never commits or tags; it prints the follow-up git commands.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() {
    echo "error: $*" >&2
    exit 1
}

_version="${1:-}"
[[ "$_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "usage: scripts/bump-version.sh <X.Y.Z>  (e.g. scripts/bump-version.sh 2.1.0)"

_date="$(date +%F)"

# VERSION file (v-prefixed, matching `git describe --tags` output format).
echo "v$_version" > "$DIR/VERSION"

# Frontend: package.json + package-lock.json (npm keeps both in sync;
# --no-git-tag-version prevents npm from committing or tagging).
# Tolerate "Version not changed" so re-running a bump stays idempotent.
_npm_out="$(cd "$DIR/frontend" && npm version "$_version" --no-git-tag-version 2>&1)" \
    || [[ "$_npm_out" == *"Version not changed"* ]] \
    || die "npm version failed: $_npm_out"

# CHANGELOG: stamp [Unreleased] with the new version and date (skip when the
# version heading already exists, so re-runs stay idempotent).
if grep -q "^## \[$_version\]" "$DIR/CHANGELOG.md"; then
    echo "note: CHANGELOG.md already has [$_version]; left unchanged"
elif grep -q '^## \[Unreleased\]' "$DIR/CHANGELOG.md"; then
    sed -i "s/^## \[Unreleased\]$/## [Unreleased]\n\n## [$_version] - $_date/" \
        "$DIR/CHANGELOG.md"
else
    echo "warning: no [Unreleased] section in CHANGELOG.md; left unchanged" >&2
fi

echo "Bumped to $_version:"
echo "  VERSION               -> v$_version"
echo "  frontend/package.json -> $_version (lockfile synced)"
echo "  CHANGELOG.md          -> [$_version] - $_date"
echo "  backend               -> dynamic (APP_VERSION build arg); no file to bump"
echo
echo "Next steps:"
echo "  git add VERSION frontend/package.json frontend/package-lock.json CHANGELOG.md"
echo "  git commit -m \"chore: bump version to $_version\""
echo "  git tag v$_version"
echo "  git push origin main --tags   # CI tags images: $_version, sha-<sha>, latest"
