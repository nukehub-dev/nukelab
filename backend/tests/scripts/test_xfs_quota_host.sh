#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# =============================================================================
# XFS Project Quota Integration Test — Run on a host with root access
# =============================================================================
# This script creates a 512MB loopback XFS image, mounts it with prjquota,
# and exercises the xfs_quota commands that NukeLab uses.
#
# Uses -D for a custom projects file (keeps host /etc/projects clean).
#
# Requirements: xfsprogs, root privileges
# Usage: sudo ./test_xfs_quota_host.sh
# =============================================================================

set -euo pipefail

IMG="/tmp/nukelab-xfs-test.img"
MNT="/tmp/nukelab-xfs-test-mnt"
CUSTOM_PROJ="/tmp/nukelab-test-projects"
VOL_DIR="$MNT/nukelab-vol-test"

cleanup() {
    echo "Cleaning up..."
    umount "$MNT" 2>/dev/null || true
    rm -f "$IMG"
    rm -rf "$MNT"
    rm -f "$CUSTOM_PROJ"
}
trap cleanup EXIT

echo "=== NukeLab XFS Project Quota Host Test ==="
echo

# Check requirements
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run as root (required for mount/loop device)"
    exit 1
fi

if ! command -v mkfs.xfs &>/dev/null; then
    echo "ERROR: mkfs.xfs not found. Install xfsprogs."
    exit 1
fi

# Step 1: Create 512MB image file
echo "[1/7] Creating 512MB image file..."
dd if=/dev/zero of="$IMG" bs=1M count=512 status=none

# Step 2: Create XFS filesystem
echo "[2/7] Creating XFS filesystem..."
mkfs.xfs -f -q "$IMG"

# Step 3: Create mount point
echo "[3/7] Creating mount point..."
mkdir -p "$MNT"

# Step 4: Mount with prjquota
echo "[4/7] Mounting with prjquota..."
mount -o loop,prjquota "$IMG" "$MNT"

if mount | grep "$MNT" | grep -q prjquota; then
    echo "      ✓ prjquota mount option confirmed"
else
    echo "      ✗ prjquota NOT active on mount"
    exit 1
fi

# Step 5: Create volume directory
echo "[5/7] Creating volume directory..."
mkdir -p "$VOL_DIR"

# Step 6: Set up project using custom file via -D
echo "[6/7] Setting up XFS project quota with -D..."
echo "10000:$VOL_DIR" > "$CUSTOM_PROJ"

xfs_io -c "chattr +P" "$VOL_DIR"

xfs_quota -x -D "$CUSTOM_PROJ" -c "project -s -p $VOL_DIR 10000" "$MNT"
xfs_quota -x -D "$CUSTOM_PROJ" -c "limit -p bhard=5m 10000" "$MNT"

# Step 7: Verify quota
echo "[7/7] Verifying quota..."
REPORT=$(xfs_quota -x -D "$CUSTOM_PROJ" -c "report -p -b -N -L 10000 -U 10000" "$MNT")
echo "      Quota report: $REPORT"

# Test enforcement: try to write 6MB
echo
echo "=== Enforcement Test ==="
echo "Writing 3MB (should succeed)..."
dd if=/dev/zero of="$VOL_DIR/test1.bin" bs=1M count=3 status=none
echo "      ✓ 3MB written successfully"

echo "Writing another 3MB (should hit 5MB limit and fail)..."
if dd if=/dev/zero of="$VOL_DIR/test2.bin" bs=1M count=3 status=none 2>/dev/null; then
    echo "      ✗ ERROR: Write succeeded — quota not enforced!"
    exit 1
else
    echo "      ✓ Write failed as expected (EDQUOT / No space left)"
fi

# Show final state
echo
echo "=== Final State ==="
ls -lh "$VOL_DIR"
xfs_quota -x -D "$CUSTOM_PROJ" -c "report -p -b -N -L 10000 -U 10000" "$MNT"

echo
echo "=== ALL TESTS PASSED ==="
echo "XFS project quotas work correctly with -D custom file."
