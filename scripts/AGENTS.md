# Scripts

## Purpose

`nukelabctl` dispatcher, shared shell library, build helpers, security scanners, and per-command modules that orchestrate the NukeLab stack.

## Ownership

All files under `scripts/`, plus the top-level `nukelabctl` dispatcher.

## Local Contracts

- Bash 4+; modules in `scripts/manage.d/*.sh` are sourced by the dispatcher, not executed directly.
- `scripts/lib.sh` is the single source of truth for shared helpers (env loading, engine detection, state persistence, logging, venv provisioning).
- Each management command exposes `cmd_<name>`, `help_<name>`, and `parse_<name>_args` when it accepts flags.
- Security scanning helpers live in `scripts/security/`.

## Work Guidance

- 4-space indent; `case` labels indented; redirects spaced (`> /dev/null`); binary operators (`&&` / `||`) may start a line. `shfmt` enforces this via `.editorconfig`.
- Every `scripts/manage.d/*.sh` module starts with `#!/bin/bash` for shellcheck.
- Add new shared helpers to `scripts/lib.sh`; do not duplicate them across modules.
- Unknown flags must be rejected with `die "Unknown option for <cmd>: $arg"`; never silently swallow them.
- `set -E` ERR trap is active; append `|| true` when invoking tools that legitimately return non-zero (e.g., `shfmt -l`, `git describe`).
- `_acquire_lock` uses `flock` on a persistent fd (noclobber pidfile fallback); modules must not replace the dispatcher's EXIT/INT/TERM traps — lock cleanup chains through `_release_lock` from the existing traps.
- Do not hardcode the version string or names of named volumes/services; use `_nukelab_version` and `_backend_services`. Discover compose-managed volumes via the `com.docker.compose.project` label rather than hardcoded name prefixes.
- `_backend_services` returns a space-separated string meant to word-split; do not quote it at the call site (`# shellcheck disable=SC2086`).
- When adding or changing `nukelabctl` commands, targets, or flags, update
  `scripts/nukelabctl-completion.bash` so bash tab-completion stays in sync.

## Verification

```bash
./nukelabctl selftest
./nukelabctl lint shell
```

## Child NAD Index

- None
