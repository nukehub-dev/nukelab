# Planning

## Purpose

Project roadmap, implementation status, and long-range planning documents. This folder captures what has been delivered, what is in flight, and what is intentionally deferred.

## Ownership

All files under `docs/plan/`. The `docs/AGENTS.md` owns the top-level docs index and cross-folder structure; this `AGENTS.md` owns the planning folder.

## Local contracts

- Markdown documents; ASCII diagrams are preferred so they remain readable offline and diff-friendly.
- Internal links must be relative.
- Do not duplicate architecture, operations, or security details that already exist under `docs/architecture/`, `docs/operations/`, or `docs/security/`. Link instead.
- Roadmap items must indicate status (`Complete`, `In Progress`, `Deferred`, `Future`).
- Decision log entries must include date, decision, rationale, and current status.

## Structure

| Document | Purpose |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Current platform status, recent milestones, and upcoming priorities |
| [IMPLEMENTATION-PHASES.md](IMPLEMENTATION-PHASES.md) | Phase-by-phase delivery record with remaining work |
| [DECISION-LOG.md](DECISION-LOG.md) | Architecture and process decisions with rationale |

## Work guidance

- Update `ROADMAP.md` after each release or milestone.
- Move completed phases into `IMPLEMENTATION-PHASES.md` and mark them complete.
- Record new reversible decisions in `DECISION-LOG.md`; update status if a decision is revised.
- Prefer deletion over stale historical notes; move historical context to an explicit "Historical" appendix with a removal date.

## Verification

- Manual review for accuracy and stale content.
- CI runs markdown lint and link checks on pull requests.

## Child NAD Index

- None.
