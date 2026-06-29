# AGENTS.md

Guidance for AI agents (and human contributors) working in this repository.

## Required tooling

Install once before making changes:

- **podman** or **docker** + matching compose (podman-compose / docker-compose).
  `CONTAINER_ENGINE=docker` overrides auto-detection if you have both.
- **Node.js** + npm (frontend only).
- **shellcheck** — shell static analysis (`./nukelabctl lint shell`).
- **shfmt** — shell formatter (`./nukelabctl lint shell --fix`).

The backend Python toolchain (ruff, bandit, pip-audit, pytest, etc.) is run
inside containers; you do **not** need a local Python venv. Lint and security
commands auto-provision `backend/.venv-dev` only when a host-side invocation
needs a tool that isn't installed globally.

## Before committing

Run these from the repo root. They are the canonical "did I break anything"
checks:

```bash
./nukelabctl lint all       # ruff (backend) + eslint/prettier (frontend) + shellcheck/shfmt (shell)
./nukelabctl test all       # frontend unit tests + backend pytest suite in a one-off container
./nukelabctl selftest       # nukelabctl sanity check + shellcheck + shfmt strict
```

Notes:

- `lint all` is the default target. Use `lint <backend|frontend|shell>` to
  scope.
- `lint <target> --fix` auto-fixes where possible. For shell that means
  `shfmt -w` (shellcheck findings are reported but never auto-applied).
- `selftest` enables shfmt strict mode by default. Set
  `NUKELAB_STRICT_FMT=0` to downgrade to a warning when prototyping.
- `test backend <paths/flags…>` forwards the rest of argv to pytest, e.g.
  `./nukelabctl test backend tests/services/test_volume_service.py -x -v`.
  Frontend has no per-file passthrough — run `cd frontend && npm run test --
  path/to/file.test.ts` directly.

## Shell style

- 4-space indent, `case` labels indented, redirects spaced (`> /dev/null`),
  binary ops (`&&` / `||`) may start a line. Configured via `.editorconfig`;
  `shfmt` reads it automatically — no flags needed.
- Every `scripts/manage.d/*.sh` module starts with `#!/bin/bash` (used by
  shellcheck; modules are sourced, not executed directly).
- New commands go in `scripts/manage.d/<cmd>.sh` with `cmd_<name>` and
  `help_<name>`. Hyphens in the command name map to underscores in the
  function name (e.g. `db-migrate` → `cmd_db_migrate`). The dispatcher in
  `nukelabctl` handles loading.
- Per-command flag parsers are `parse_<name>_args` and are called by
  `_dispatch_command`. **Always add one** if your command accepts any flags
  — unknown options must be rejected, not silently dropped (see the `rm`
  regression fixed in this branch for context).

## Architecture pointer

- `nukelabctl` — top-level dispatcher; argument parsing, command bootstrap,
  and trap/cleanup setup.
- `scripts/lib.sh` — shared helpers: env loading, engine detection, state
  persistence, logging, concurrency lock, preflight, dev venv. New helpers
  that >1 command needs go here (avoids drift — see `_ensure_dev_venv` which
  was previously duplicated in lint.sh and security.sh).
- `scripts/manage.d/*.sh` — one file per command. Sourced on demand.

## Common pitfalls

- **`set -E` ERR trap**: any un-absorbed non-zero exit aborts the script,
  even inside `$(...)`. When invoking a tool that legitimately returns
  non-zero (e.g. `shfmt -l` when files need formatting, `git describe` in a
  tag-less repo), append `|| true`.
- **`_backend_services` returns a space-separated string**; it's meant to
  word-split when passed to `$COMPOSE ... <services>`. Don't quote it at
  the call site — there's a `# shellcheck disable=SC2086` comment.
- **Dev and prod share container names**; only one stack may run at a time.
  `_require_other_stack_stopped` enforces this.
- **Frontend tests don't accept argv passthrough** through `nukelabctl test
  frontend`. If you need to scope a frontend test, invoke npm directly.

## Security & penetration testing

The project maintains a comprehensive penetration test plan in
`docs/PENETRATION-TEST-PLAN.md`. When adding security features or addressing
findings:

- Keep `docs/PENETRATION-TEST-PLAN.md` in sync with implemented controls and
current scope decisions.
- Track individual findings in `docs/PENETRATION-TEST-FINDINGS.md` and
remediation ownership in `docs/PENETRATION-TEST-REMEDIATION.md`.
- Add regression tests for every confirmed finding under
`backend/tests/security/` so it cannot silently regress.
- Use `./nukelabctl security` as the canonical dependency/container scanning
  checkpoint; extend it rather than adding one-off scanners.
- Use `./nukelabctl verify-hardening [container]` to confirm spawned server
  containers are hardened (non-root, no capabilities, read-only rootfs,
  no-new-privileges).
- Container escape, network pivoting, and daemon-level tests must run in an
isolated environment or CI job, never against a shared production stack.

### Verifying container hardening in a dev stack

Container hardening is gated by `CONTAINER_HARDENING_ENABLED`. In production it
defaults to **enabled**; in dev mode it defaults to **disabled** so local
iteration is not blocked. To verify hardening against a local dev stack:

1. Ensure `.env.development` contains `CONTAINER_HARDENING_ENABLED=true` (it
   should already).
2. Start the dev stack: `./nukelabctl up dev`.
3. Create a server through the API/UI.
4. Verify the running container:
   ```bash
   ./nukelabctl verify-hardening <container_name>
   ```
   Expected output: `User: 65532:65532`, `CapDrop: [ALL]`, `ReadonlyRootfs: true`,
   `SecurityOpt: [no-new-privileges:true]`, `Container uid: uid=65532(nukelab)`,
   and `Container capability sets are zeroed`.
5. If you need the raw inspect values, the command is equivalent to:
   ```bash
   podman inspect <container_name> --format '{{.Config.User}} {{.HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.SecurityOpt}}'
   ```
   Expected: `65532:65532 [ALL] true [no-new-privileges:true]`.
6. Inside the container, run `id` and `cat /proc/self/status | grep Cap`.
   Expected: `uid=65532(nukelab)` and all capability sets zeroed.

The regression test `backend/tests/security/test_container_isolation.py` mocks
the Docker client directly; run it inside the backend test container with
`--confcutdir=tests/security` to avoid the root `conftest.py` Postgres/Redis
fixtures.

### CI/CD supply-chain checks

The security command now supports optional supply-chain checks. Enable them in
release pipelines:

- `./nukelabctl security --check-base-images` — fail if external Dockerfile
  `FROM` images are not pinned by digest.
- `./nukelabctl security --signed-commits` — fail if the current branch contains
  unsigned commits.
- `./nukelabctl security --sbom` — generate CycloneDX SBOMs under
  `backend/reports/security/sbom/`.

These checks are off by default because they require process/registry changes
(commit signing and base-image pinning) that are not yet enforced.

## What NOT to do

- Don't write a per-command parser that swallows unknown options as a
  warning — use `die "Unknown option for <cmd>: $arg"` to match the rest of the
  codebase.
- Don't hardcode the version string or names of named volumes / services —
  use `_nukelab_version` / `compose config --volumes` / `_backend_services`.
- Don't duplicate venv/bootstrap helpers across modules — add them to
  `scripts/lib.sh` so there's one source of truth.
- Don't add penetration-test findings as code comments; record them in
  `docs/PENETRATION-TEST-FINDINGS.md` with a proper CVSS rating and retest
  criteria.

