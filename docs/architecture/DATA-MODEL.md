# NukeLab Data Model

This document describes the core entities and schema conventions. For the full SQL schema, see `backend/database/schema.sql`. The API exposes these entities through Pydantic models under `backend/app/schemas/`.

## Entity overview

```
┌─────────┐     ┌─────────┐     ┌─────────────┐       ┌─────────┐
│  User   │────►│  Role   │     │ Environment │       │  Plan   │
└────┬────┘     └─────────┘     └──────┬──────┘       └────┬────┘
     │                                 │                   │
     │    ┌────────────────────────────┘                   │
     │    │                                                │
     ▼    ▼                                               ▼
  ┌───────┐     ┌─────────────┐      ┌──────────────┐    ┌──────────────┐
  │ Server│────►│    Volume   │◄────│SharedWorkspace│    │ Credit       │
  └───┬───┘     └─────────────┘      │              │    │ Transaction  │
      │                              └──────────────┘    └──────────────┘
      │
      ▼
  ┌────────────┐
  │ Audit Log  │
  └────────────┘
```

## User

Represents a platform account.

```python
class User:
    id: UUID
    username: str              # Unique, URL-safe
    email: str
    full_name: str
    role: str                  # References Role.name
    permissions: list[str]     # Override permissions
    groups: list[UUID]         # Organization groups
    max_cpu: int
    max_memory: str
    max_disk: str
    max_gpu: int
    max_servers: int
    nuke_balance: int
    daily_allowance: int
    last_nuke_reset: datetime
    profile: dict              # Avatar, timezone, department, etc.
    preferences: dict          # Theme, language, defaults
    security: dict             # MFA, last IP, failed attempts, locked_until
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
```

## Role

A named collection of permissions. Roles are seeded at install and can be customized by super admins.

```python
class Role:
    name: str                  # e.g., "admin", "user"
    permissions: list[str]
    is_system: bool            # True for built-in roles
    level: int                 # Higher level = more privilege
```

## Server

Represents a user container.

```python
class Server:
    id: UUID
    name: str
    user_id: UUID
    environment_id: UUID
    plan_id: UUID
    container_id: str
    image: str
    status: ServerStatus       # pending, starting, running, stopping, stopped, error
    allocated_cpu: float
    allocated_memory: str
    allocated_disk: str
    allocated_gpu: int
    max_runtime: str
    idle_timeout: str
    internal_port: int         # Theia port, typically 3000
    external_url: str          # /user/{username}/{server_id}
    health_status: str
    health_check_config: dict
    last_health_check: datetime
    status_reason: str
    stopped_by: UUID
    stop_reason: str
    started_at: datetime
    stopped_at: datetime
    last_activity: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
```

## Environment

Admin-created template that defines the container image, packages, and settings for a server.

```python
class Environment:
    id: UUID
    name: str
    slug: str
    description: str
    image: str
    dockerfile: str            # Optional custom Dockerfile
    packages: list[str]
    env_vars: dict[str, str]
    volumes: list[str]
    ports: list[int]
    icon: str
    color: str
    category: str
    is_active: bool
    is_public: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime
```

## Plan

Resource tier independent of environment.

```python
class Plan:
    id: UUID
    name: str                  # e.g., "small", "medium", "large"
    description: str
    cpu: float
    memory: str
    disk: str
    gpu: int
    max_runtime: str
    idle_timeout: str
    allow_scheduling: bool
    allow_snapshots: bool
    priority: str              # low, normal, high
    min_role: str
    max_per_user: int
    requires_approval: bool
    is_active: bool
    is_default: bool
    display_order: int
    nukes_per_hour: int
    created_at: datetime
    updated_at: datetime
```

## Volume

Persistent storage attached to servers or shared by workspaces.

```python
class Volume:
    id: UUID
    name: str
    user_id: UUID               # Owner
    max_size_bytes: int
    used_bytes: int
    mount_path: str
    is_active: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime
```

## Shared Workspace

A group-owned volume with member and invitation management.

```python
class SharedWorkspace:
    id: UUID
    name: str
    owner_id: UUID
    volume_id: UUID
    members: list[WorkspaceMember]
    invitations: list[WorkspaceInvitation]
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

## Credit Transaction

Immutable NUKE ledger entry.

```python
class CreditTransaction:
    id: UUID
    timestamp: datetime
    user_id: UUID
    amount: int                 # Positive = credit, negative = debit
    balance_after: int
    type: str                   # daily_allowance, server_usage, admin_grant, purchase, refund
    description: str
    server_id: UUID
    plan_id: UUID
    actor_id: UUID
    metadata: dict
```

## Audit Log

Immutable record of admin/support actions.

```python
class AuditLog:
    id: UUID
    timestamp: datetime
    actor_id: UUID
    actor_username: str
    actor_role: str
    action: str
    target_type: str
    target_id: UUID
    target_name: str
    before_state: dict
    after_state: dict
    ip_address: str
    user_agent: str
    success: bool
    error_message: str
    request_id: UUID
```

## Schema conventions

- Primary keys are UUIDs generated by `gen_random_uuid()`.
- Time-series tables (`activity_logs`, `server_metrics`, `request_metrics`) are range-partitioned by month.
- Each partitioned table has a `DEFAULT` partition as a safety net.
- JSONB columns store flexible or extensible data (`profile`, `preferences`, `security`, `metadata`).
- Audit and credit tables are append-only; application code does not update or delete rows.
- Foreign keys enforce referential integrity; deletion of referenced rows is typically restricted or set to soft-delete.

## Related documents

- [SERVER-LIFECYCLE.md](SERVER-LIFECYCLE.md) for how entities transition through states
- [AUTH.md](AUTH.md) for user and role authorization details
- [operations/OPERATIONS.md](../operations/OPERATIONS.md) for database profiling and partition management
- `backend/database/schema.sql` for the complete schema
