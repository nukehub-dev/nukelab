# Planning

## Purpose

Project roadmap, implementation status, and long-range planning documents. This folder captures what has been delivered, what is in flight, and what is intentionally deferred.

## Ownership

All files under `docs/plan/`. The `docs/AGENTS.md` owns the top-level docs index and cross-folder structure; this `AGENTS.md` owns the planning folder.

## Local contracts

- Markdown documents; ASCII diagrams are preferred so they remain readable offline and diff-friendly.
- Internal links must be relative.
- Do not duplicate architecture, operations, or security details that already exist under `docs/architecture/`, `docs/operations/`, or `docs/security/`. Link instead.
- Roadmap items must indicate status (`Complete`, `Partial`, `In Progress`, `Deferred`, `Future`). `Partial` means runnable pieces exist but the stated end-to-end capability is incomplete.
- Implementation status must cite repository evidence. Models, flags, notification helpers, or test files alone do not establish a delivered workflow. Distinguish tests present from tests wired into CI, and static inspection from executed verification.
- Decision log entries must include date, decision, rationale, and current status.

## Structure

| Document | Purpose |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Current platform status, recent milestones, and upcoming priorities |
| [IMPLEMENTATION-PHASES.md](IMPLEMENTATION-PHASES.md) | Phase-by-phase delivery record with remaining work |
| [DECISION-LOG.md](DECISION-LOG.md) | Architecture and process decisions with rationale |

## Work guidance

- Update `ROADMAP.md` after each release or milestone.
- Keep `IMPLEMENTATION-PHASES.md` as the existing historical delivery summary and correct stale capability claims. Do not append temporary execution phases or cycle logs; keep current shared priorities in `ROADMAP.md` and follow the root local-research rule for working materials.
- Record new reversible decisions in `DECISION-LOG.md`; update status if a decision is revised.
- Prefer deletion over stale historical notes; move historical context to an explicit "Historical" appendix with a removal date.

## Verification

- Manual review for accuracy and stale content.
- CI runs markdown lint and link checks on pull requests.

## Child NAD Index

- None.
