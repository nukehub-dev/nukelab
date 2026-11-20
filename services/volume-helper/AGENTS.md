# Volume Recovery Helper

## Purpose

Bounded capture and restore of detached private user volumes.

## Ownership

The helper image, command implementation and its focused tests. Backend services own authorization, durable exclusion, quotas, runtime identity and publication of public operation state.

## Local Contracts

- Run as UID/GID 65532 with no network, capabilities, writable root filesystem or Docker socket.
- Source mounts are read-only with copy-up disabled. Restore targets are new, empty, protected volumes; image directory ownership seeds normal target ownership through Docker copy-up.
- Only fixed container paths and service-generated UUIDs are command arguments. User names and paths never select mounts or artifact locations.
- Capture rejects unreadable/unsupported data and never changes source permissions. Completed archives publish by atomic rename; partial files are not restore points.
- Capture bounds generated PAX metadata with the same limit used by restore so a completed artifact remains admissible under its recorded limits.
- Restore verifies fixed checksum bytes and the complete bounded archive graph using the backend archive module, then copies into a fresh target while preserving supported links and safe modes.
- The helper cannot release a durable guard. Its caller must prove termination before cleanup or release; elapsed time alone is insufficient.

## Work Guidance

Build from the repository root so the image copies the reviewed backend archive module. Keep the source and helper module version together.

## Verification

- Unit/security checks: `python -m pytest services/volume-helper/test_helper.py --confcutdir=services/volume-helper`.
- Runtime contract checks: `./nukelabctl test backend tests/security/test_volume_recovery_runtime.py --confcutdir=tests/security`.
- Real Docker checks require an isolated daemon and an explicit local `NUKELAB_VOLUME_HELPER_TEST_IMAGE`; run `test_docker.py` as documented in the README. The fixture must verify labels before removing only its own resources.

## Child NAD Index

- None.
