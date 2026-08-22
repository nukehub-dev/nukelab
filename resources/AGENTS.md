# Resources

## Purpose

Native/shared resources used by the platform, currently the `libnukelab_cpu` helper library.

## Ownership

All files under `resources/`.

## Local Contracts

- C source and Makefile under `resources/lib/nukelab/`.
- `libnukelab_cpu.so` is gitignored; the canonical build happens inline inside `environments/base/Dockerfile` during the base image build.
- Source of truth for compilation flags is the Makefile; keep it in sync with the inline build stage in `environments/base/Dockerfile`.

## Work Guidance

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
