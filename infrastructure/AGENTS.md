# Infrastructure

## Purpose

Reverse proxy, TLS, and network infrastructure configuration that routes traffic into the NukeLab stack.

## Ownership

All files under `infrastructure/`.

## Local Contracts

- Traefik v3 static configuration in `traefik/traefik.yml`.
- Dynamic configuration (routers, services, middlewares) in `traefik/dynamic/`.
- TLS and certificate handling orchestrated at the project level; `certs/` is the certificate output directory.

## Work Guidance

- Put middleware definitions in `traefik/dynamic/middlewares.yml`.
- Do not enable the Traefik dashboard insecurely; dashboard and `api.insecure` labels must remain absent from default config.
- Avoid the `browserXssFilter` header because it creates XS-Leak side channels.
- Security headers should be enforced by the backend middleware where possible; Traefik headers are a defense-in-depth layer.

## Verification

- Manual review of config syntax and security posture.
- `./scripts/generate-certs.sh` can be used to generate local TLS assets.

## Child NAD Index

- None
