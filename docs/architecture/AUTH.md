# NukeLab Authentication and Authorization

NukeLab uses a dual authentication strategy: **local username/password** for development and **OAuth 2.0 / OIDC** for production. Both paths produce an asymmetrically signed JWT that the RBAC system consumes.

## Local authentication flow

```
Browser
  |
  v
React login form
  |
  v
POST /api/auth/login
  |
  v
FastAPI
  |
  +---> bcrypt password verification
  |
  +---> Generate EdDSA-signed JWT
        |
        v
      Client stores access token + refresh token
        |
        v
      Subsequent requests send Authorization: Bearer <token>
```

Local auth is controlled by `AUTH_MODE=local` or `AUTH_MODE=both`. The dev admin account is auto-created when `DEV_MODE=true`.

## OAuth / OIDC authentication flow

```
Browser
  |
  v
React app redirects to OAuth provider
  |
  v
OAuth provider (Keycloak, Auth0, Okta, Authentik, etc.)
  |
  v
Provider redirects to /api/auth/oauth/callback
  |
  v
FastAPI validates authorization code + PKCE
  |
  v
FastAPI fetches user info and issues local JWT
  |
  v
Client stores tokens and uses them for API calls
```

OAuth configuration supports OIDC Discovery via `OAUTH_DISCOVERY_URL`, or manual endpoint configuration. PKCE is enabled by default.

## JWT design

Access tokens are signed with **EdDSA (Ed25519)**. Key pairs are stored in a Docker named volume mounted at `/run/user-secrets`.

- `JWT_EXPIRE_MINUTES` controls access token lifetime (default 15 minutes).
- Platform refresh tokens are hashed and stored in the PostgreSQL
  `refresh_tokens` table; OAuth provider refresh tokens are encrypted with a key
  derived from `JWT_SECRET` and stored in the user's `security` data.
- Redis holds the access-token denylist and revocation cutoffs, not the refresh
  tokens. `USER_AUTH_DENYLIST_FAIL_CLOSED=true` causes requests to fail if Redis
  is unavailable.

## RBAC overview

Roles are predefined and map to a permission matrix. Super admins can customize
role permissions through the persisted `role_permissions` override; individual
users do not have permission override fields.

| Role | Typical access |
|---|---|
| `super_admin` | Full system access (`*`), including cross-user server access |
| `admin` | Full user, server, environment, plan, volume, workspace and credit management; cross-user NukeIDE access still requires `servers:access_others` |
| `moderator` | User read/create/update, full server/catalog/quota management, audit read; cannot delete users, impersonate, or mint cross-user NukeIDE tokens |
| `support` | User read, server read-all and own-server writes, credit grants, volume/workspace read-all and own writes; no cross-user server access by default |
| `user` | Own servers, volumes and workspaces; read public environments/plans; own credits/analytics |
| `guest` | Own server/volume read only; no automatic expiry job |

## Permission examples

```
users:read              - View user list and profiles
users:create            - Create users
users:update            - Update users, including enable/disable
users:delete            - Permanently delete users
servers:read_own        - View own servers
servers:write_own       - Start/stop/edit/delete own servers
servers:read_all        - View all servers
servers:write_all       - Manage all server records
servers:access_others   - Mint a NukeIDE access token for another user's server
environment:create      - Create environment templates
plan:update             - Edit plans, subject to the last-usable-plan guard
audit:read              - View audit logs
admin:access            - Open the administration area
```

API-token scopes are a separate vocabulary (`servers:read`, `servers:start`,
`servers:stop`, `servers:delete`, `servers:manage`, `volumes:read`,
`volumes:manage`, etc.) defined in `app/api/tokens.py`. A token request must
satisfy both its scopes and the owner's RBAC permissions.

## NukeIDE container access

Each user container runs nginx on port 8080; its `auth_request` subrequest is
handled by the local Go auth sidecar on port 8081, which validates the
short-lived server token before forwarding to the Theia IDE.

```
User Request ---> Traefik ---> NukeIDE Container :8080
                                     |
                                     v
                             +---------------+
                             |  nginx proxy  |
                             |  auth_request |
                             |  /auth        |
                             +-------+-------+
                                     |
                                     v
                             +---------------+
                             |  auth sidecar |
                             |    :8081      |
                             +-------+-------+
                                     |
                                     v
                             +---------------+
                             |    Theia      |
                             +---------------+
```

The backend issues and audits server tokens, but does not validate every
container request. The sidecar validates the RS256 signature locally with the
mounted public key. Keys live in the `nukelab-server-secrets` volume and token
lifetime defaults to 5 minutes (`SERVER_AUTH_TOKEN_TTL`). Key rotation is
operator-driven; `SERVER_AUTH_KEY_ROTATION_DAYS` is a configuration value, not
an automatic scheduler.

## CSRF protection

For requests authenticated via cookies (not Bearer tokens), the backend enforces a double-submit CSRF token:

- The client obtains a token from `GET /api/auth/csrf-token`; login itself sets
  only the session cookie.
- State-changing requests must include the same value in the `X-CSRF-Token`
  header.
- Safe methods (GET, HEAD, OPTIONS) and requests using Bearer auth are exempt.

## Authorization checks in code

Routes and services check permissions through FastAPI dependencies. The auth module loads the current user, validates the token, and exposes helper dependencies for common permission sets.

## Related documents

- [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for how auth integrates with container access
- [DATA-MODEL.md](DATA-MODEL.md) for user and role entities
- [security/USER-AUTH-KEYS.md](../security/USER-AUTH-KEYS.md) for key management details
- `.env.example` for all auth-related environment variables
