# Services

## Purpose

Auxiliary services that run alongside the main NukeLab stack (for example, authentication sidecars, proxies, or future service boundaries).

## Ownership

All directories under `services/`.

## Local Contracts

- Each service is a self-contained runtime with its own `Dockerfile`, source, and README.
- Services are built via `scripts/services/build-*.sh` helpers or the CI/CD pipeline.
- Service-specific language conventions are owned by the child `AGENTS.md`.

## Work Guidance

- Keep each service's README current with build and run instructions.
- Prefer minimal, hardened images; align with the container hardening guidance in the root `AGENTS.md`.
- Add service-specific tests or verification steps to the service's child `AGENTS.md`.

## Verification

- Per-service checks listed in child docs.

## Child NAD Index

- `auth-sidecar/` — Go-based authentication sidecar.
