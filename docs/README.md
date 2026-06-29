# NukeLab Documentation

This directory contains all durable documentation for the NukeLab platform. Documentation is organized by audience and purpose so readers can find what they need without wading through unrelated detail.

## How to use this index

- **New contributors and developers** → start with [development/LOCAL-DEV.md](development/LOCAL-DEV.md) and [development/CONTRIBUTING.md](development/CONTRIBUTING.md)
- **Operators running the platform** → start with [architecture/OVERVIEW.md](architecture/OVERVIEW.md), then [operations/OPERATIONS.md](operations/OPERATIONS.md)
- **Security reviewers** → start with [security/PENETRATION-TEST-PLAN.md](security/PENETRATION-TEST-PLAN.md)
- **Anyone configuring or deploying** → see [reference/ENV-VARS.md](reference/ENV-VARS.md) and [operations/PRODUCTION-DEPLOYMENT.md](operations/PRODUCTION-DEPLOYMENT.md)

## Documentation structure

### Architecture

| Document | Purpose |
|---|---|
| [architecture/OVERVIEW.md](architecture/OVERVIEW.md) | High-level system overview, request flow, and runtime boundaries |
| [architecture/COMPONENTS.md](architecture/COMPONENTS.md) | Component responsibilities and interaction matrix |
| [architecture/AUTH.md](architecture/AUTH.md) | Authentication and authorization flows: local JWT, OAuth, container access proxy |
| [architecture/SERVER-LIFECYCLE.md](architecture/SERVER-LIFECYCLE.md) | Server spawn, start, stop, restart, delete, and scheduling flows |
| [architecture/DATA-MODEL.md](architecture/DATA-MODEL.md) | Core entities, relationships, and schema conventions |
| [architecture/MONITORING.md](architecture/MONITORING.md) | Observability stack: Prometheus, Grafana, Alertmanager, Jaeger, OpenTelemetry |

### Operations

| Document | Purpose |
|---|---|
| [operations/OPERATIONS.md](operations/OPERATIONS.md) | Day-to-day database operations, profiling, tuning, and scaling |
| [operations/PRODUCTION-DEPLOYMENT.md](operations/PRODUCTION-DEPLOYMENT.md) | Production deployment, cgroup controllers, lxcfs, storage quotas |
| [operations/BACKUP-RESTORE.md](operations/BACKUP-RESTORE.md) | Backup strategies, restore procedures, and disaster recovery |
| [operations/READ-REPLICAS.md](operations/READ-REPLICAS.md) | Read replica reference for future scaling |

### Security

| Document | Purpose |
|---|---|
| [security/PENETRATION-TEST-PLAN.md](security/PENETRATION-TEST-PLAN.md) | Scope, methodology, and test plan for security reviews |
| [security/PENETRATION-TEST-FINDINGS.md](security/PENETRATION-TEST-FINDINGS.md) | Confirmed findings with CVSS ratings and retest criteria |
| [security/PENETRATION-TEST-REMEDIATION.md](security/PENETRATION-TEST-REMEDIATION.md) | Remediation ownership and tracking |
| [security/OWASP-AUDIT.md](security/OWASP-AUDIT.md) | OWASP-aligned security audit notes |
| [security/USER-AUTH-KEYS.md](security/USER-AUTH-KEYS.md) | User authentication key management |

### Development

| Document | Purpose |
|---|---|
| [development/LOCAL-DEV.md](development/LOCAL-DEV.md) | Development stack, hot reload, and local tooling |
| [development/CONTRIBUTING.md](development/CONTRIBUTING.md) | How to contribute: tests, lint, commit style, PR process |

### Reference

| Document | Purpose |
|---|---|
| [reference/ENV-VARS.md](reference/ENV-VARS.md) | Environment variable descriptions and quick reference |
| [reference/CLI-COMMANDS.md](reference/CLI-COMMANDS.md) | `nukelabctl` command reference and common examples |

## Maintenance rules

1. **Keep architecture docs in sync with code.** A PR that changes a documented flow, component boundary, auth mechanism, or data model must update the corresponding architecture document or explain why it is not necessary.
2. **Prefer deletion over stale historical notes.** If a section no longer reflects current behavior, delete it or move it to an explicit "Historical" appendix with a removal date.
3. **Do not duplicate details that live elsewhere.** API endpoints are documented at `/api/docs`. Environment variables are described in `.env.example`. CLI commands are surfaced by `./nukelabctl --help`. Link to those sources instead of copying them.
4. **Use relative links.** All internal links must be relative so documentation remains usable offline and in branches.

See [AGENTS.md](AGENTS.md) for ownership and contract details.
