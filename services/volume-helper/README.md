# Volume recovery helper

Release images are published as
`ghcr.io/nukehub-dev/nukelab-volume-helper:<version>` (and `latest`). Pin
`VOLUME_BACKUP_HELPER_IMAGE` to that reference for pull-based deployments, or
build locally with the CI helper, which applies the correct per-Dockerfile
ignore handling for Docker and Podman:

```bash
./scripts/ci/e2e-stack.sh build
```

For a manual Docker/BuildKit build from the repository root:

```bash
docker build -f services/volume-helper/Dockerfile -t nukelab-volume-helper:latest .
```

On Podman versions that support it, add
`--ignorefile services/volume-helper/Dockerfile.dockerignore` to keep the build
context limited to the reviewed helper and archive sources.

The backend resolves this trusted image to an immutable local ID before use.
The runtime supplies fixed mounts, UUID operation identities, bounded limits and
network/resource hardening. It does not expose a generic shell command endpoint.
The Dockerfile-specific build context includes only the helper and reviewed
archive module; the repository's default context excludes backend source.

Capture mounts `/source` read-only without Docker copy-up and writes only its
private `/artifact` directory. Restore mounts the completed artifact at `/archive`
read-only, operation staging at `/artifact`, and a fresh volume at `/target`.
Docker copy-up from the image's empty UID 65532 target directory initializes the
new volume; existing source ownership is never changed.

Artifacts contain gzip tar data plus private completion metadata. Restored data
uses the platform UID/GID and safe owner-only permissions. Relative symlinks with
no parent components and hardlinks to earlier regular members are supported;
sockets, devices, FIFOs and sparse tar formats are not. Unreadable source data
fails the operation rather than publishing an incomplete recovery point.

These are offline recovery copies, not filesystem snapshots or off-host backups.
The host operator must not mutate source storage or helper mounts out of band.

Run focused tests with Python, pytest and the backend source available:

```bash
python -m pytest services/volume-helper/test_helper.py --confcutdir=services/volume-helper
```

On an isolated local/CI Docker daemon, opt into the real hardened data test:

```bash
NUKELAB_VOLUME_HELPER_TEST_IMAGE=nukelab-volume-helper:latest \
  python -m pytest services/volume-helper/test_docker.py --confcutdir=services/volume-helper
```

The test creates unique labelled volumes and containers, verifies capture/restore
and hardening, and deletes only its own resources. Fixture preparation uses a
separate root container to initialize disposable directory ownership; both
recovery executors run with the production unprivileged configuration.
