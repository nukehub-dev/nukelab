# Decision Log

Reversible architecture and process decisions for NukeLab v2.0.

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-04-27 | FastAPI over Django | Better async/WS performance for Docker API calls | Approved |
| 2026-04-27 | Next.js 16 over 14 | Turbopack stable, Cache Components, React Compiler | Revised |
| 2026-04-29 | Vite + React 19 SPA over Next.js | Zero Node.js runtime, RAM savings, TanStack ecosystem | Approved |
| 2026-04-27 | Traefik v3 over Nginx | Dynamic routing, Kubernetes-ready | Approved |
| 2026-04-27 | PostgreSQL 18 | Latest stable, improved JSONB performance | Approved |
| 2026-04-27 | Nginx auth agent in containers | Self-contained auth, fast validation | Approved |
| 2026-04-27 | Local auth for dev | Easy testing without NukeHub Auth | Approved |
| 2026-04-27 | Separate dev environment | Fast builds for testing | Approved |
| 2026-04-27 | Server Plans separate from Environments | Flexible resource allocation per environment | Approved |
| 2026-04-27 | NUKE currency system | Fair resource allocation on limited hardware | Approved |
| 2026-04-27 | Queue-based scheduling | Handle resource scarcity gracefully | Approved |
| 2026-04-27 | Daily NUKE allowance with no rollover | Prevent hoarding, encourage fair use | Approved |
| 2026-04-27 | User Preferences/Defaults | Save default environment/plan/settings per user | Approved |
| 2026-05-15 | JWT-only for bulk/sensitive admin ops | Bulk actions are high-impact and require session auth | Approved |
| 2026-05-15 | `Alt+N` over `Ctrl+N` for quick spawn | Avoids Firefox "New Window" and OS shortcut collisions | Approved |
| 2026-05-20 | Extracted spawner helpers for bulk ops | Reuse lifecycle logic instead of duplicating orchestration | Approved |
| 2026-05-24 | DataTable row selection for bulk actions | Consistent UX pattern across tables | Approved |
