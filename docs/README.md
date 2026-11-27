# NukeLab Documentation

This directory contains all durable documentation for the NukeLab platform. Documentation is organized by audience and purpose so readers can find what they need without wading through unrelated detail.

## How to use this index

- **New contributors and developers** → [Local development](development/LOCAL-DEV.md) and [Contributing guide](development/CONTRIBUTING.md)
- **Operators running the platform** → [System overview](architecture/OVERVIEW.md) and [Operations guide](operations/OPERATIONS.md)
- **Security reviewers** → [Penetration test plan](security/PENETRATION-TEST-PLAN.md)
- **Anyone configuring or deploying** → [Environment variables](reference/ENV-VARS.md) and [Production deployment](operations/PRODUCTION-DEPLOYMENT.md)

## Documentation structure

### Plan

| Document | Purpose |
|---|---|
| [Roadmap](plan/ROADMAP.md) | Current release baseline, product priorities, operational readiness, and deferred work |
| [Implementation phases](plan/IMPLEMENTATION-PHASES.md) | Phase-by-phase delivery record with remaining work |
| [Decision log](plan/DECISION-LOG.md) | Architecture and process decisions with rationale |

### Architecture

| Document | Purpose |
|---|---|
| [System overview](architecture/OVERVIEW.md) | High-level system overview, request flow, and runtime boundaries |
| [Components](architecture/COMPONENTS.md) | Component responsibilities and interaction matrix |
| [Authentication and authorization](architecture/AUTH.md) | Local JWT, OAuth, and the container access proxy |
| [Server lifecycle](architecture/SERVER-LIFECYCLE.md) | Queue admission, fenced lifecycle, provenance/recreation, heartbeats, proof-backed recovery and admin operations |
| [Data model](architecture/DATA-MODEL.md) | Core entities, relationships, and schema conventions |
| [Monitoring](architecture/MONITORING.md) | Prometheus, Grafana, Alertmanager, Jaeger, and OpenTelemetry |

### Operations

| Document | Purpose |
|---|---|
| [Operations guide](operations/OPERATIONS.md) | First-run catalog setup, recovery operations, upgrades and rollback, database operations, monitoring and supply-chain checks |
| [Production deployment](operations/PRODUCTION-DEPLOYMENT.md) | Production deployment, cgroup controllers, lxcfs, storage quotas and optional volume recovery |
| [Backup and restore](operations/BACKUP-RESTORE.md) | Database and private-volume backup, restore procedures, reconciliation and disaster recovery |
| [GPU setup](operations/GPU-SETUP.md) | NVIDIA GPU passthrough and CDI configuration |
| [Read replicas](operations/READ-REPLICAS.md) | Read replica reference for future scaling |

### Security

| Document | Purpose |
|---|---|
| [Penetration test plan](security/PENETRATION-TEST-PLAN.md) | Scope, methodology, and test plan for security reviews |
| [Penetration test findings](security/PENETRATION-TEST-FINDINGS.md) | Confirmed findings with CVSS ratings and retest criteria |
| [Penetration test remediation](security/PENETRATION-TEST-REMEDIATION.md) | Remediation ownership and tracking |
| [OWASP audit](security/OWASP-AUDIT.md) | OWASP-aligned security audit notes |
| [User authentication keys](security/USER-AUTH-KEYS.md) | User authentication key management |

### Development

| Document | Purpose |
|---|---|
| [Local development](development/LOCAL-DEV.md) | Development stack, hot reload, and local tooling |
| [Contributing guide](development/CONTRIBUTING.md) | Tests, lint, commit style, and pull requests |
| [Web Push](development/WEB-PUSH.md) | Browser push notification setup and service-worker behavior |

### Reference

| Document | Purpose |
|---|---|
| [Environment variables](reference/ENV-VARS.md) | Configuration for recovery, registry verification, queueing and the rest of the platform |
| [CLI reference](reference/CLI-COMMANDS.md) | `nukelabctl` commands and examples |

## Maintenance rules

1. **Keep architecture docs in sync with code.** A PR that changes a documented flow, component boundary, auth mechanism, or data model must update the corresponding architecture document or explain why it is not necessary.
2. **Prefer deletion over stale historical notes.** If a section no longer reflects current behavior, delete it or move it to an explicit "Historical" appendix with a removal date.
3. **Do not duplicate details that live elsewhere.** API endpoints are documented at `/api/docs`. Environment variables are described in `.env.example`. CLI commands are surfaced by `./nukelabctl --help`. Link to those sources instead of copying them.
4. **Use relative links.** All internal links must be relative so documentation remains usable offline and in branches.

See the [documentation contributor instructions](AGENTS.md) for ownership and contract details.
