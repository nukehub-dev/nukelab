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
| `assets/` | Everyone | Theme-aware README architecture SVGs, local brand icons, and the SVG generator source |

## Work guidance

- Keep `architecture/` in sync with code changes. A PR that modifies a documented flow, component boundary, auth mechanism, or data model must update the corresponding architecture document or explain why it is not necessary.
- The root `README.md` architecture overview uses `docs/assets/architecture-light.svg` and `architecture-dark.svg` through a `<picture>` wrapper. Generate both from `docs/assets/build-architecture-svg.py`; do not hand-edit the generated SVGs. Keep them free of remote CDNs, remote icons, and external requests; the brand icons are embedded as data URIs.
- Keep `PENETRATION-TEST-PLAN.md` in sync with implemented security controls and current scope.
- Record confirmed findings in `PENETRATION-TEST-FINDINGS.md` with CVSS ratings and retest criteria.
- Track remediation ownership in `PENETRATION-TEST-REMEDIATION.md`.
- Prefer operational, current guidance over historical notes; delete stale text rather than explaining history.
- Do not add penetration-test findings as code comments; record them here.
- Update this `AGENTS.md` when the docs structure or ownership changes.

## Verification

- Manual review for accuracy and stale content.
- When changing the README architecture block, run `python3 docs/assets/build-architecture-svg.py`, preview both SVGs in light and dark, and check mobile width.
- Run `python3 docs/assets/build-architecture-svg.py --check` before committing generated assets.
- Run `./nukelabctl lint markdown` after documentation edits; it runs the same
  Markdown lint and link checks as CI.
- Run `./nukelabctl lint shell` if any shell scripts (not fenced examples) are
  changed.

## Child NAD Index

- `plan/AGENTS.md` — roadmap, implementation phases, and decision log

`architecture/`, `operations/`, `security/`, and `development/` do not yet have
dedicated child contracts; this document owns them until those boundaries
warrant separate files.
