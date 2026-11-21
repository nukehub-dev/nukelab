#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Generate a normalized CycloneDX JSON SBOM for a published container image.
#
# The SBOM contains the installed package/library inventory; file catalogers
# are excluded so large environment images stay within the attestation size
# budget. The generator is pinned by tag and digest. The target must be a
# digest-qualified registry reference so the SBOM describes the published
# artifact rather than a mutable tag. Serialization is normalized (serial
# number derived from the image digest, timestamp removed, keys sorted) so the
# same generator version and image digest produce the same SBOM bytes.
#
# This script is the release path. It fails on generator errors, missing or
# empty output, non-CycloneDX JSON, and SBOMs with no components. It never
# swallows failures.
#
# Usage:
#   ./scripts/security/generate-release-sbom.sh \
#     --image-ref ghcr.io/owner/nukelab-backend@sha256:<digest> \
#     --output sbom-backend.cdx.json
#
# Options:
#   --image-ref <ref>  Digest-qualified image reference to scan (required)
#   --output <path>    CycloneDX JSON output path (required)
#   -h, --help         Show this help message
#
# Environment:
#   CONTAINER_ENGINE  Container engine to use (default: podman, then docker)
#   DOCKER_CONFIG     Directory containing registry config.json for generator
#                     authentication (default: ${HOME}/.docker)

set -euo pipefail

SBOM_GENERATOR_IMAGE="ghcr.io/anchore/syft:v1.57.2@sha256:e97e20b6e6d1699c60296b66ab337941724f9bd06ac279d893eda89601fc4b2a"
SBOM_FORMAT="cyclonedx-json"

image_ref=""
output=""

die() {
    echo "ERROR: $*" >&2
    exit 1
}

show_help() {
    cat << EOF
${0}: Generate a deterministic CycloneDX SBOM for a published image.

Usage: ${0} --image-ref <ref> --output <path>

Options:
  --image-ref <ref>  Digest-qualified image reference to scan (required)
  --output <path>    CycloneDX JSON output path (required)
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image-ref)
            [[ $# -ge 2 ]] || die "--image-ref requires a value"
            image_ref="$2"
            shift 2
            ;;
        --image-ref=*)
            image_ref="${1#*=}"
            shift
            ;;
        --output)
            [[ $# -ge 2 ]] || die "--output requires a value"
            output="$2"
            shift 2
            ;;
        --output=*)
            output="${1#*=}"
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

[[ -n "$image_ref" ]] || die "--image-ref is required"
[[ -n "$output" ]] || die "--output is required"

# The subject must be the exact published digest, not a tag. This keeps the
# SBOM tied to the same image identity as the provenance attestation.
if [[ ! "$image_ref" =~ ^[a-zA-Z0-9._:/-]+@sha256:[0-9a-f]{64}$ ]]; then
    die "Image reference must be registry/image@sha256:<64 hex characters>: ${image_ref}"
fi

engine="${CONTAINER_ENGINE:-}"
if [[ -z "$engine" ]]; then
    if command -v podman > /dev/null 2>&1; then
        engine=podman
    elif command -v docker > /dev/null 2>&1; then
        engine=docker
    else
        die "No container engine found; set CONTAINER_ENGINE or install docker/podman"
    fi
fi
command -v "$engine" > /dev/null 2>&1 || die "Container engine not found: ${engine}"

command -v python3 > /dev/null 2>&1 || die "python3 is required for SBOM normalization"

mkdir -p "$(dirname "$output")"
output_dir="$(cd "$(dirname "$output")" && pwd)"
output="${output_dir}/$(basename "$output")"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/nukelab-sbom.XXXXXX")"
cleanup() {
    rm -rf "$tmp_dir"
}
trap cleanup EXIT INT TERM

raw_sbom="${tmp_dir}/raw.cdx.json"
normalized_sbom="${tmp_dir}/normalized.cdx.json"

# Registry credentials written by docker/login-action live in the host Docker
# config. Mount them read-only for private registries; public images work
# anonymously.
docker_config="${DOCKER_CONFIG:-${HOME}/.docker}/config.json"
run_args=(
    run --rm
    -v "${tmp_dir}:/sbom-output:rw"
)
if [[ -f "$docker_config" ]]; then
    run_args+=(-v "${docker_config}:/root/.docker/config.json:ro")
fi
run_args+=(
    -e DOCKER_CONFIG=/root/.docker
    "$SBOM_GENERATOR_IMAGE" scan "$image_ref"
    # Keep the release SBOM to installed package/library inventory. File
    # catalogers add tens of thousands of file entries to large environment
    # images, exceed the attestation size budget, and are not dependencies.
    --select-catalogers -file
    --output "${SBOM_FORMAT}=/sbom-output/raw.cdx.json"
    --quiet
)

echo "Generating CycloneDX SBOM for ${image_ref}"
"$engine" "${run_args[@]}"

[[ -s "$raw_sbom" ]] || die "SBOM generator produced no output for ${image_ref}"

python3 - "$raw_sbom" "$normalized_sbom" "$image_ref" << 'PY'
import json
import sys
import uuid

raw_path, normalized_path, image_ref = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    with open(raw_path, encoding="utf-8") as handle:
        document = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    sys.exit(f"Invalid SBOM JSON from generator: {exc}")

if document.get("bomFormat") != "CycloneDX":
    sys.exit("Generator output is not a CycloneDX document")

components = document.get("components")
if not isinstance(components, list) or not components:
    sys.exit("CycloneDX document has no components")

# actions/attest requires a non-empty serialNumber to recognize CycloneDX.
# Replace the generator's random UUID with a deterministic one derived from the
# image digest, remove the run timestamp, and canonicalize serialization so the
# same generator version and image digest produce the same bytes.
document["serialNumber"] = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, image_ref))
metadata = document.get("metadata")
if isinstance(metadata, dict):
    metadata.pop("timestamp", None)

with open(normalized_path, "w", encoding="utf-8") as handle:
    json.dump(document, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    handle.write("\n")

print(f"CycloneDX components: {len(components)}")
PY

# actions/attest rejects SBOM files larger than 16 MiB. Fail here with a clear
# message instead of failing later in the attestation step.
max_sbom_bytes=16777216
sbom_bytes="$(wc -c < "$normalized_sbom")"
if ((sbom_bytes > max_sbom_bytes)); then
    die "SBOM is ${sbom_bytes} bytes; actions/attest accepts at most ${max_sbom_bytes} bytes"
fi

mv "$normalized_sbom" "$output"
echo "SBOM written to ${output} (${sbom_bytes} bytes)"
