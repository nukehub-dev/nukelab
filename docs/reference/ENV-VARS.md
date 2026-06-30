# Environment Variables Reference

This document groups and explains the environment variables used by NukeLab. The authoritative source is `.env.example`; when in doubt, check that file.

## Quick start

```bash
cp .env.example .env.development   # Local development
cp .env.example .env               # Production
```

Both `.env` and `.env.development` are gitignored. `.env.example` is the only environment file tracked in Git.

## Variable groups

### Application

| Variable | Description |
|---|---|
| `APP_NAME` | Application name |
| `APP_ENV` | `development`, `staging`, or `production` |
| `APP_DEBUG` | Enable debug output; `false` in production |
| `APP_URL` | Public application URL |
| `FRONTEND_URL` | Optional separate frontend URL for Vite dev server |
| `APP_TIMEZONE` | Default timezone |

### Security

| Variable | Description |
|---|---|
| `JWT_SECRET` | Encrypts OAuth refresh tokens; must be changed in production |
| `JWT_EXPIRE_MINUTES` | Access token lifetime |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh token lifetime |
| `USER_AUTH_KEY_ALGORITHM` | `EdDSA` for asymmetric access token signing |
| `USER_AUTH_SECRETS_DIR` | Path to Ed25519 key pair volume |
| `USER_AUTH_DENYLIST_FAIL_CLOSED` | Reject auth if Redis is unavailable |
| `SESSION_SECRET` | Cookie signing secret; must be changed in production |
| `SESSION_MAX_AGE` | Session cookie lifetime in seconds |
| `SESSION_SECURE` | HTTPS-only cookies |
| `SECURITY_HEADERS_ENABLED` | Inject security headers from FastAPI |
| `CSRF_PROTECTION_ENABLED` | Enable double-submit CSRF protection |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `CORS_ALLOW_CREDENTIALS` | Allow cookies across origins |
| `RATE_LIMIT_ENABLED` | Enable rate limiting |
| `RATE_LIMIT_REQUESTS` | Requests per rate limit window |
| `RATE_LIMIT_WINDOW` | Rate limit window in seconds |

### Authentication

| Variable | Description |
|---|---|
| `AUTH_MODE` | `local`, `oauth`, or `both` |
| `LOCAL_AUTH_BCRYPT_ROUNDS` | bcrypt cost factor |
| `DEV_MODE` | Auto-create dev admin account |
| `DEV_ADMIN_USER` / `DEV_ADMIN_PASSWORD` | Dev admin credentials |

### OAuth / OIDC

| Variable | Description |
|---|---|
| `OAUTH_PROVIDER_NAME` | Display name on login screen |
| `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` | Provider credentials |
| `OAUTH_DISCOVERY_URL` | OIDC discovery endpoint |
| `OAUTH_AUTHORIZE_URL` / `OAUTH_TOKEN_URL` / `OAUTH_USERDATA_URL` / `OAUTH_LOGOUT_URL` | Manual endpoints when discovery is unused |
| `OAUTH_CALLBACK_URL` | Redirect URI registered with provider |
| `OAUTH_SCOPE` / `OAUTH_USERNAME_CLAIM` / `OAUTH_EMAIL_CLAIM` / `OAUTH_NAME_CLAIM` / `OAUTH_PICTURE_CLAIM` | Claim mapping |
| `OAUTH_PKCE_ENABLED` | Enable PKCE |

### Database

| Variable | Description |
|---|---|
| `DATABASE_USER` / `DATABASE_PASSWORD` / `DATABASE_NAME` / `DATABASE_HOST` / `DATABASE_PORT` | PostgreSQL connection |
| `DATABASE_URL` | Optional full asyncpg URL |
| `DATABASE_POOL_SIZE` / `DATABASE_POOL_MAX_OVERFLOW` / `DATABASE_POOL_TIMEOUT` / `DATABASE_POOL_RECYCLE` / `DATABASE_POOL_PRE_PING` | SQLAlchemy pool settings |
| `DATABASE_QUERY_TIMEOUT_SECONDS` | Query abort threshold |
| `DATABASE_ECHO` | Log all SQL |
| `OBSERVABILITY_SLOW_QUERY_THRESHOLD_MS` | Slow query log threshold |
| `OBSERVABILITY_PG_STAT_STATEMENTS_ENABLED` | Track statements with pg_stat_statements |

### PgBouncer

| Variable | Description |
|---|---|
| `PGBOUNCER_ENABLED` | Enable PgBouncer overlay |
| `PGBOUNCER_POOL_MODE` | Must be `transaction` for asyncpg |
| `PGBOUNCER_MAX_CLIENT_CONN` / `PGBOUNCER_DEFAULT_POOL_SIZE` / `PGBOUNCER_RESERVE_POOL_SIZE` / `PGBOUNCER_MAX_DB_CONNECTIONS` | Pool sizing |
| `PGBOUNCER_*` | Timeouts, TCP keepalive, stats, container resources |

### Redis

| Variable | Description |
|---|---|
| `REDIS_URL` | Redis connection URL |
| `REDIS_PASSWORD` | Optional Redis password |
| `REDIS_DB` | Redis database number |
| `REDIS_MAXMEMORY` | Memory limit |
| `REDIS_MAXMEMORY_POLICY` | Eviction policy, e.g., `allkeys-lru` |

### Frontend / CDN

| Variable | Description |
|---|---|
| `VITE_CDN_URL` | Optional CDN origin for static JS/CSS assets |

### Docker / Podman

| Variable | Description |
|---|---|
| `DOCKER_SOCKET` | Container engine socket; empty for auto-detection |
| `DOCKER_NETWORK` | Network name for spawned containers |
| `DOCKER_REGISTRY` | Optional image registry |
| `DOCKER_PULL_POLICY` | `always`, `if-not-present`, or `never` |
| `COMPOSE_OVERLAYS` | Space-separated extra compose files |
| `VOLUME_STORAGE_PATH` | Host path for volume file operations |
| `XFS_QUOTA_ENABLED` | Enable kernel-enforced XFS project quotas |
| `UPLOAD_DIR` | Container path for uploads |

### Server container authentication

| Variable | Description |
|---|---|
| `SERVER_AUTH_ENABLED` | Enable short-lived server tokens |
| `SERVER_AUTH_SECRETS_DIR` | Path to RS256 key volume |
| `SERVER_AUTH_TOKEN_TTL` | Server token lifetime in seconds |
| `SERVER_AUTH_KEY_ALGORITHM` | `RS256` or `ES256` |
| `SERVER_AUTH_KEY_ROTATION_DAYS` | Automatic key rotation interval |
| `SERVER_AUTH_MAX_TOKENS_PER_MINUTE` | Rate limit for server token issuance |

### Monitoring

| Variable | Description |
|---|---|
| `PROMETHEUS_ENABLED` | Expose `/api/metrics` |
| `GRAFANA_ENABLED` | Start Grafana container |
| `REQUEST_METRICS_STORE` | `prometheus`, `database`, or `both` |

See `.env.example` for the full list, defaults, and inline documentation.

## Related documents

- [LOCAL-DEV.md](../development/LOCAL-DEV.md) for development setup
- [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for production-specific guidance
- `.env.example` for the complete template
