# Resources

## Purpose

Native/shared resources used by the platform, currently the `libnukelab_cpu` helper library.

## Ownership

All files under `resources/`.

## Local Contracts

- C source, Makefile, and Dockerfile under `resources/lib/nukelab/`.
- `libnukelab_cpu.so` is gitignored; the canonical build happens in the `nukelab-cpu-lib` image built by `scripts/resources/build-cpu-lib.sh`.
- `environments/base/Dockerfile` consumes the `nukelab-cpu-lib` image via `COPY --from`.
- Source of truth for compilation flags is the Makefile; keep it in sync with `resources/lib/nukelab/Dockerfile`.

## Work Guidance

- Build the image with `./scripts/resources/build-cpu-lib.sh`.
- Build locally with `make` from `resources/lib/nukelab/` for development/testing.
- Update `README.md` when build steps or ABI change.
- Keep the library focused on deterministic, side-effect-free helper operations.

## Verification

```bash
cd resources/lib/nukelab
make
```

## Child NAD Index

- None
