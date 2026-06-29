# Backend

## Purpose

Python FastAPI backend for the NukeLab platform: REST API, WebSocket events, business logic, SQLAlchemy models, Alembic migrations, Celery background tasks, and container orchestration via the Docker SDK.

## Ownership

All files under `backend/` except generated artifacts (`.venv-dev`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `htmlcov`, `logs`).

## Local Contracts

- Python 3.12+; formatting and linting configured in `pyproject.toml`.
- `app/main.py` is the ASGI entry point.
- `app/api/` owns route definitions; `app/services/` owns business logic; `app/models/` owns SQLAlchemy models; `app/db/` owns session/connection logic; `app/core/` owns cross-cutting utilities; `app/middleware/` owns ASGI middleware; `app/container/` owns Docker orchestration; `app/tasks.py` and `app/worker.py` own Celery.
- `alembic/` owns database migrations; use Alembic commands to generate and test upgrades/downgrades.
- `tests/` mirrors the `app/` structure; security regressions go in `tests/security/`.

## Work Guidance

- Run backend tests with `./nukelabctl test backend [pytest args]`.
- Run backend lint with `./nukelabctl lint backend` (ruff via container or host venv).
- Add regression tests for every confirmed security finding under `tests/security/`.
- Use `app/dependencies.py` for FastAPI dependency injection.
- Keep middleware concerns in `app/middleware/`; do not inline ASGI logic in `main.py`.
- Database migrations must be reversible and tested against the current schema.
- Prefer structured logging via `app/core/logging`; avoid `print()` in production code.
- Environment config lives in `app/config.py`; read values from there, not directly from `os.environ`.

## Verification

```bash
./nukelabctl lint backend
./nukelabctl test backend
```

## Child NAD Index

- None
