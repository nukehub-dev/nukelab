# Resources

## Purpose

Native/shared resources used by the platform, currently the `libnukelab_cpu` helper library.

## Ownership

All files under `resources/`.

## Local Contracts

- C source and Makefile under `resources/lib/nukelab/`.
- Compiled artifacts (`.so`) may be committed when stable; source of truth is the Makefile.

## Work Guidance

- Build with `make` from `resources/lib/nukelab/`.
- Update `README.md` when build steps or ABI change.
- Keep the library focused on deterministic, side-effect-free helper operations.

## Verification

```bash
cd resources/lib/nukelab
make
```

## Child NAD Index

- None
