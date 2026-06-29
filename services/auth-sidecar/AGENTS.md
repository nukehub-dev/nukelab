# Auth Sidecar

## Purpose

Go-based authentication sidecar service that validates requests before they reach the backend.

## Ownership

All files under `services/auth-sidecar/`.

## Local Contracts

- Go modules (`go.mod` / `go.sum`); single binary built from `main.go`.
- `Dockerfile` defines the container image; built via `scripts/build-auth-sidecar.sh` or CI.

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
