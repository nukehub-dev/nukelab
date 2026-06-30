# Docs

## Purpose

Durable project documentation: architecture, operations, deployment, security records, and developer guides.

## Ownership

All files under `docs/`. The `docs/AGENTS.md` owns the docs structure; each subfolder owns its own content and must stay in sync with the code it describes.

## Local contracts

- Markdown documents; ASCII diagrams are preferred so they remain readable offline and diff-friendly.
- Security documents use the naming convention `PENETRATION-TEST-*.md`.
- Internal links must be relative.
- Do not duplicate information that lives in `.env.example`, generated API docs (`/api/docs`), or `./nukelabctl --help`. Link instead.

## Structure

| Folder | Audience | Content |
|---|---|---|
| `architecture/` | Developers, operators, security reviewers | System overview, components, auth, server lifecycle, data model, monitoring |
| `operations/` | Operators | Day-to-day operations, production deployment, backup/restore, scaling reference |
| `security/` | Security reviewers, auditors | Penetration test plans, findings, remediation, OWASP audit, auth key management |
| `development/` | Contributors | Local development setup, contributing workflow |
| `plan/` | Product owners, leads, contributors | Roadmap, implementation status, decision log |
| `reference/` | Everyone | Environment variable and CLI command quick reference |

## Work guidance

- Keep `architecture/` in sync with code changes. A PR that modifies a documented flow, component boundary, auth mechanism, or data model must update the corresponding architecture document or explain why it is not necessary.
- Keep `PENETRATION-TEST-PLAN.md` in sync with implemented security controls and current scope.
- Record confirmed findings in `PENETRATION-TEST-FINDINGS.md` with CVSS ratings and retest criteria.
- Track remediation ownership in `PENETRATION-TEST-REMEDIATION.md`.
- Prefer operational, current guidance over historical notes; delete stale text rather than explaining history.
- Do not add penetration-test findings as code comments; record them here.
- Update this `AGENTS.md` when the docs structure or ownership changes.

## Verification

- Manual review for accuracy and stale content.
- CI runs markdown lint and link checks on pull requests.
- Run `./nukelabctl lint shell` if any shell examples in docs are changed.

## Child NAD Index

- `architecture/AGENTS.md` — future subfolder contract if architecture grows beyond these files
- `operations/AGENTS.md` — future subfolder contract if operations docs grow
- `security/AGENTS.md` — future subfolder contract if security docs grow
- `development/AGENTS.md` — future subfolder contract if development docs grow
- `plan/AGENTS.md` — roadmap, implementation phases, and decision log

Currently these subfolders do not have dedicated `AGENTS.md` files except `plan/`; this document owns the remainder.
