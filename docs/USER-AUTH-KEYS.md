# User Auth Keys

This document covers the EdDSA (Ed25519) key pair used to sign user access tokens.

## Overview

User access tokens are short-lived JWTs signed with an Ed25519 private key that lives only in the backend container. The corresponding public keys are published via:

- `/api/auth/jwks.json` — JSON Web Key Set for external verification.
- `/api/auth/public-key.pem` — Current active public key in PEM format.

The backend maintains a small **key ring**: the active signing key plus any recently-retired public keys. This allows zero-downtime key rotation: tokens signed just before rotation continue to validate until their normal expiry or until the retired public key is cleaned up.

## Key files

Default locations (inside the backend container):

| File | Purpose |
|------|---------|
| `/run/user-secrets/user-auth-private.pem` | Active signing key (private, backend only) |
| `/run/user-secrets/user-auth-public.pem` | Active verification key |
| `/run/user-secrets/user-auth-public-<kid>.pem` | Retired verification key (kept during grace period) |

The `kid` is the first 16 hex characters of the SHA-256 hash of the public-key PEM.

The user-auth keys are stored in a separate Docker named volume (`nukelab-user-secrets`) from the server-auth keys (`nukelab-server-secrets`) so a compromise of one key does not expose the other.

## Provisioning in production

1. Generate a strong Ed25519 key pair outside the container:

   ```bash
   openssl genpkey -algorithm Ed25519 -out user-auth-private.pem
   openssl pkey -in user-auth-private.pem -pubout -out user-auth-public.pem
   chmod 600 user-auth-private.pem
   chmod 644 user-auth-public.pem
   ```

2. Mount them into the backend container at the configured paths (default `/run/user-secrets`).

3. Ensure the environment is production:

   ```env
   APP_ENV=production
   USER_AUTH_SECRETS_DIR=/run/user-secrets
   ```

The backend will refuse to start in production if:

- The private or public key file is missing.
- The private key file has group or other permissions (`chmod 600` is required).

## Rotation

Rotate the active signing key without invalidating in-flight tokens:

```bash
./nukelabctl rotate-user-auth-key
```

This runs inside the backend container and:

1. Loads the current active public key and derives its `kid`.
2. Generates a fresh Ed25519 key pair.
3. Moves the old public key to `user-auth-public-<old_kid>.pem`.
4. Writes the new active private/public PEMs.
5. Secure-deletes the old private key.

The key manager detects the changed active private key on the next signing/verification call and reloads the key ring automatically.

### Cleanup

After the grace period (default: 2 × `JWT_EXPIRE_MINUTES`), retired public keys can be removed:

```bash
./nukelabctl cleanup-user-auth-keys
```

This removes any `user-auth-public-<kid>.pem` file older than `USER_AUTH_KEY_ROTATION_GRACE_SECONDS`.

## Revocation

Two mechanisms are available:

### JTI denylist

Every access token has a unique JWT ID (`jti`). When a user logs out, their current access token's `jti` is added to a Redis denylist with a TTL equal to the token's remaining lifetime.

Key: `nukelab:token:deny:<jti>`

### User-level cutoff

When a user's password changes, role changes, or account is deactivated, a cutoff timestamp is stored per user. Any access token with an `iat` (issued-at) time at or before the cutoff is rejected.

Key: `nukelab:token:revoke:user:<username>`

TTL: 2 × `JWT_EXPIRE_MINUTES`.

Admins can also revoke all tokens for a user via:

```bash
curl -X POST -H "Authorization: Bearer <admin-token>" \
  https://nukelab.example.com/api/admin/users/<username>/revoke-tokens
```

## Redis dependency

Authenticated traffic now depends on Redis for revocation checks.

- By default (`USER_AUTH_DENYLIST_FAIL_CLOSED=true`), a Redis outage causes authenticated requests to be rejected with `401 Unauthorized`.
- Set `USER_AUTH_DENYLIST_FAIL_CLOSED=false` to keep accepting authenticated requests during a Redis outage. Revoked tokens could slip through in that mode.

Public/guest endpoints are not affected by Redis outages.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `USER_AUTH_SECRETS_DIR` | `/run/user-secrets` | Directory holding user-auth keys |
| `USER_AUTH_LEEWAY_SECONDS` | `5` | Clock-skew tolerance for JWT `exp`/`iat` |
| `USER_AUTH_DENYLIST_FAIL_CLOSED` | `true` | Reject auth traffic when Redis is unreachable |
| `USER_AUTH_KEY_ROTATION_GRACE_SECONDS` | `2 × JWT_EXPIRE_MINUTES` | How long retired public keys are kept |
