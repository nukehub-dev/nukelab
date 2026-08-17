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
| 2026-08-14 | Separate `nukelab-environments` repository + runtime composition for scientific images | Keeps platform repo focused on runtime; toolchain images mount into `nukelab-workspace` at spawn time so workspace/IDE updates do not force MOAB/Geant4/OpenMC rebuilds; k3s-compatible via init-container volume population | Approved |
| 2026-08-14 | Toolchain volume locking, stamp invalidation, and hardened helper containers | Cross-process lock container prevents racing populates; image-ID stamp invalidates stale volumes on tag re-push; hash-suffixed volume names prevent truncation collisions; helper containers drop capabilities so shared-volume content cannot be poisoned via privileged helpers | Approved |
| 2026-08-15 | Toolchain datasets under `/opt/nuke/data/<name>`; separate shared data volume deferred | OpenMC cross-sections/chain files move from `/opt/nuke/openmc_data` to `/opt/nuke/data/openmc`; Geant4 datasets stay under `/opt/nuke/geant4/share/data` (Geant4-native discovery via `geant4.sh`/compiled datadir). A dedicated data volume (independent code/data refresh, sharing datasets across toolchain versions) is deferred until dataset size/cadence justifies multi-volume manifests. Open follow-up: verify Geant4 per-dataset `G4*` env vars reach composed runtime containers (source `geant4.sh` from `toolchain-env.sh` if missing) at the next nuclear-base rebuild | Deferred |
