# Auth Sidecar

## Purpose

Go-based authentication sidecar service that validates requests before they reach the backend.

## Ownership

All files under `services/auth-sidecar/`.

## Local Contracts

- Go modules (`go.mod` / `go.sum`); single binary built from `main.go`.
- `Dockerfile` defines the container image; built via `scripts/services/build-auth-sidecar.sh` or CI.
- `/auth` and `/validate` record allowed requests to an in-memory `last_activity` timestamp, exposed via `GET /activity`; the backend idle-shutdown task polls it (`app/tasks.py:_fetch_sidecar_activity`). `/health` and `/metrics` must never update it.

## Work Guidance

- Follow standard Go formatting (`gofmt`) and conventions.
- Keep the sidecar stateless; configuration via environment variables.
- Update `README.md` when build or deployment behavior changes.

## Verification

```bash
cd services/auth-sidecar
go build ./...
go test ./... 2>/dev/null || true
```

## Child NAD Index

- None
