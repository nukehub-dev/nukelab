# NukeLab Auth Sidecar

Authentication sidecar for NukeLab server containers.

## Overview

The auth sidecar validates short-lived, server-scoped JWT access tokens locally within each container. It uses asymmetric cryptography (RS256) where:

- **Backend** holds the private key and signs tokens
- **Sidecar** holds the public key and validates tokens
- **Containers** never see the main JWT secret

## Architecture

```
+---------+      +---------+
| Browser | ---> | Traefik |
+---------+      +----+----+
                      |
                      v
+-----------------------------------------------------------+
|                    Server Pod                             |
|                                                           |
|  +---------+     auth      +---------------------------+  |
|  |  Nginx  | <-----------> |      Auth Sidecar         |  |
|  +----+----+               +---------------------------+  |
|       |                                                   |
|       v                                                   |
|  +---------+                                              |
|  |  ttyd   |                                              |
|  +---------+                                              |
+-----------------------------------------------------------+
```

## Security Features

- **Asymmetric cryptography** (RS256) - private key never leaves backend
- **Server-scoped tokens** - each token is only valid for one specific server
- **Short-lived** - 5 minute default expiry
- **No backend dependency** - validates locally without network calls
- **Rate limiting** - per-IP token validation limits
- **Minimal attack surface** - single static binary, no shell
- **Audit logging** - all token issuances tracked in database

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `NUKELAB_AUTH_SERVER_ID` | *(required)* | Server UUID for token scoping |
| `NUKELAB_AUTH_ENABLED` | `true` | Enable/disable auth |
| `NUKELAB_AUTH_PUBLIC_KEY_PATH` | `/etc/nukelab/auth/public.pem` | Path to RSA public key |
| `NUKELAB_AUTH_ALGORITHM` | `RS256` | JWT signing algorithm |
| `NUKELAB_AUTH_LISTEN_ADDR` | `:8080` | HTTP listen address |
| `NUKELAB_AUTH_RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `NUKELAB_AUTH_RATE_LIMIT_REQUESTS` | `100` | Max requests per window |
| `NUKELAB_AUTH_RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |

## Endpoints

- `GET /health` - Health check (no auth required)
- `GET /auth` - Nginx auth_request handler (returns 200/401)
- `GET /validate` - Full validation with JSON response
- `GET /metrics` - Basic metrics
- `GET /activity` - Last allowed-request timestamp (Unix seconds, `0` = none
  since start). Polled by the backend idle-shutdown task so real proxied
  traffic counts as server activity.

## Activity tracking

Every request allowed through `/auth` or `/validate` (valid token, or
auth-disabled pass-through) updates an in-memory `last_activity` timestamp.
Requests carrying an **expired but authentic** token (valid signature and
audience for this server) also update it, while still being rejected with 401 —
this keeps long IDE sessions, whose token cookie outlives its 5-minute TTL,
counted as activity. Forged tokens, wrong-audience tokens, and requests to
`/health` or `/metrics` never update it. The timestamp resets on sidecar
restart; the backend falls back to its database `last_activity` in that case.

## Building

```bash
cd services/auth-sidecar
docker build -t nukelab-auth-sidecar:latest .
```

## Testing

```bash
go test ./...
```
