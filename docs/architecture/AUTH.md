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
- Refresh tokens are encrypted with `JWT_SECRET` and stored in Redis.
- Token denylist checks are enforced against Redis; `USER_AUTH_DENYLIST_FAIL_CLOSED=true` causes requests to fail if Redis is unavailable.

## RBAC overview

Roles are predefined and map to a permission matrix. Super admins can customize permissions per role, and individual users can have permission overrides.

| Role | Typical access |
|---|---|
| `super_admin` | Full system access, can modify roles and platform config |
| `admin` | Full user/server management, can access any user server (audited) |
| `moderator` | Can CRUD users, view all resources, cannot access user servers |
| `support` | Can view users and servers, can access user servers for debugging (audited) |
| `user` | Can manage own servers and resources, limited by quotas |
| `guest` | Temporary access with severe limits and auto-expiry |

## Permission examples

```
users:read            - View user list and profiles
users:create          - Create users
users:delete          - Permanently delete users
users:disable         - Disable/enable accounts
servers:read_own      - View own servers
servers:read_all      - View all servers
servers:start         - Start a server
servers:stop          - Stop a server
servers:access_own    - Access own NukeIDE session
servers:access_all    - Access any user's NukeIDE session
environments:create   - Create environment templates
audit:read            - View audit logs
system:config         - Modify platform configuration
```

## NukeIDE container access

Each user container runs an nginx proxy that validates a short-lived, server-scoped token before forwarding to the Theia IDE.

```
User Request ---> Traefik ---> NukeIDE Container :80
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
                             |    NukeIDE    |
                             |   port 3000   |
                             +---------------+
```

The nginx `auth_request` subrequest calls `/api/auth/verify` on the FastAPI backend. The backend validates the server token and confirms that the requesting user is authorized to access that specific container.

Server tokens use asymmetric **RS256** keys stored in the `nukelab-server-secrets` volume. Token lifetime defaults to 5 minutes (`SERVER_AUTH_TOKEN_TTL`) and keys auto-rotate every 30 days (`SERVER_AUTH_KEY_ROTATION_DAYS`).

## CSRF protection

For requests authenticated via cookies (not Bearer tokens), the backend enforces a double-submit CSRF token:

- A `csrf_token` cookie is set on login.
- State-changing requests must include the same value in the `X-CSRF-Token` header.
- Safe methods (GET, HEAD, OPTIONS) and requests using Bearer auth are exempt.

## Authorization checks in code

Routes and services check permissions through FastAPI dependencies. The auth module loads the current user, validates the token, and exposes helper dependencies for common permission sets.

## Related documents

- [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for how auth integrates with container access
- [DATA-MODEL.md](DATA-MODEL.md) for user and role entities
- [security/USER-AUTH-KEYS.md](../security/USER-AUTH-KEYS.md) for key management details
- `.env.example` for all auth-related environment variables
