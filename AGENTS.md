# Nuke Agent Doc (NAD) Framework

## Purpose

Binding work contract for AI agents and human contributors working on the NukeLab platform.

## Ownership

This root `AGENTS.md` owns the NAD hierarchy, project-wide workflow rules, and cross-domain standards. Domain-specific guidance lives in child `AGENTS.md` files listed in the Child NAD Index.

## NAD Core Contract

- `AGENTS.md` files are binding work contracts for their subtrees.
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable `AGENTS.md` plus every parent `AGENTS.md` above it.

### Read Before Editing

1. Read this root `AGENTS.md`.
2. Identify every file or folder you expect to touch.
3. Walk from the repository root to each target path.
4. Read every `AGENTS.md` found along each route.
5. If a parent `AGENTS.md` lists a child `AGENTS.md` whose scope contains the path, read that child and continue from there.
6. Use the nearest `AGENTS.md` as the local contract and parent docs for repo-wide rules.
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken NAD.

### Update After Editing

Every meaningful change requires a NAD pass before the task is done.

Update the closest owning `AGENTS.md` when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- `AGENTS.md` creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the NAD pass still must happen.

## Hierarchy

- Root `AGENTS.md` is the NAD rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child NAD Index.
- Child `AGENTS.md` files own domain-specific instructions and their own Child NAD Index.
- Each parent explains what its direct children cover and what stays owned by the parent.
- The closer a doc is to the work, the more specific and practical it must be.

## Child Doc Shape

Create a child `AGENTS.md` when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards.

Default section order:

- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child NAD Index

## Style

- Keep docs concise, current, and operational.
- Document stable contracts, not diary entries.
- Put broad rules in parent docs and concrete details in child docs.
- Prefer direct bullets with explicit names.
- Do not duplicate rules across many files unless each scope needs a local version.
- Delete stale notes instead of explaining history.
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist.

## Closeout

1. Re-check changed paths against the NAD chain.
2. Update nearest owning docs and any affected parents or children.
3. Refresh every affected Child NAD Index.
4. Remove stale or contradictory text.
5. Run existing verification when relevant.
6. Report any docs intentionally left unchanged and why.

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child `AGENTS.md`.

---

# NukeLab Project Guidance

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
- Frontend has no per-file passthrough — run `cd frontend && npm run test --
  path/to/file.test.ts` directly. See `frontend/AGENTS.md` for frontend
  conventions.

## Architecture pointer

- `nukelabctl` — top-level dispatcher; argument parsing, command bootstrap,
  and trap/cleanup setup.
- `scripts/lib.sh` — shared helpers: env loading, engine detection, state
  persistence, logging, concurrency lock, preflight, dev venv. New helpers
  that >1 command needs go here.
- `scripts/manage.d/*.sh` — one file per command. Sourced on demand. See
  `scripts/AGENTS.md` for shell conventions and module rules.
- `backend/` — Python FastAPI backend, models, migrations, tests. See
  `backend/AGENTS.md`.
- `frontend/` — Vite + React 19 SPA and Playwright e2e tests. See
  `frontend/AGENTS.md`.
- `services/` — auxiliary services such as the Go auth-sidecar. See
  `services/AGENTS.md` and per-service child docs.
- `infrastructure/traefik/` — reverse proxy and network config. See
  `infrastructure/AGENTS.md`.
- `monitoring/` — Prometheus, Grafana, Alertmanager, Jaeger, OTEL. See
  `monitoring/AGENTS.md`.
- `docs/` — operational and security documentation. See `docs/AGENTS.md`.

## Common pitfalls

- **Dev and prod share container names**; only one stack may run at a time.
  `_require_other_stack_stopped` enforces this.
- Shell-specific conventions and pitfalls (ERR trap, `_backend_services`
  word-splitting, parser rules) are documented in `scripts/AGENTS.md`.

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

The security command supports optional supply-chain checks. Enable them in
release pipelines:

- `./nukelabctl security --check-base-images` — fail if external Dockerfile
  `FROM` images are not pinned by digest.
- `./nukelabctl security --signed-commits` — fail if the current branch contains
  unsigned commits.
- `./nukelabctl security --sbom` — generate CycloneDX SBOMs under
  `backend/reports/security/sbom/`.

These checks are off by default because they require process/registry changes
(commit signing and base-image pinning) that are not yet enforced.

## Child NAD Index

- `backend/AGENTS.md` — Python FastAPI backend, models, migrations, tests.
- `docs/AGENTS.md` — Project documentation and security records.
- `environments/AGENTS.md` — User environment Docker image definitions.
- `frontend/AGENTS.md` — Vite + React 19 SPA and e2e tests.
- `infrastructure/AGENTS.md` — Traefik reverse proxy and network config.
- `monitoring/AGENTS.md` — Prometheus, Grafana, Alertmanager, Jaeger, OTEL.
- `resources/AGENTS.md` — Native/shared resources (`libnukelab_cpu`).
- `scripts/AGENTS.md` — `nukelabctl`, shared library, build/security helpers.
- `services/AGENTS.md` — Auxiliary services.
- `services/auth-sidecar/AGENTS.md` — Go authentication sidecar.
