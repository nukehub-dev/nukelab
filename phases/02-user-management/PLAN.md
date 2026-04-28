# Phase 2: User Management & RBAC

**Duration**: Weeks 4-6
**Goal**: Complete user lifecycle management with granular permissions, credit system, and admin dashboard
**Status**: IN PROGRESS

---

## Overview

Phase 2 transforms the basic scaffolding from Phase 1 into a fully functional multi-user platform. This phase delivers:

- **Granular RBAC**: Permission-based access control (not just role strings)
- **User Lifecycle**: Complete CRUD with admin controls
- **Credit Economy**: Daily allowances, consumption tracking, admin grants
- **User Experience**: Preferences, profiles, settings
- **Admin Power**: Dashboard for user/server/credit management
- **Frontend Auth**: Working login flow, protected routes, role-based UI

### Phase 1 Prerequisite Fixes

Before starting Phase 2, these Phase 1 issues must be resolved:

- [ ] **Traefik Socket Mount** — Fix Podman socket path in `docker-compose.yml`
  - Current: `${DOCKER_SOCKET:-/var/run/docker.sock}`
  - Fix: Auto-detect Podman vs Docker socket path
- [ ] **Frontend Auth Flow** — Implement actual login with JWT storage
- [ ] **Server Start Endpoint** — Implement `POST /api/servers/{id}/start`

---

## Week 4: RBAC System & User CRUD

### Day 1-2: Permission System Foundation

#### Backend Tasks

- [ ] **Permission Model** (`backend/app/core/permissions.py`)
  ```python
  class Permission:
      # User management
      USERS_READ = "users:read"
      USERS_CREATE = "users:create"
      USERS_UPDATE = "users:update"
      USERS_DELETE = "users:delete"
      USERS_IMPERSONATE = "users:impersonate"
      
      # Server management
      SERVERS_READ_OWN = "servers:read_own"
      SERVERS_READ_ALL = "servers:read_all"
      SERVERS_START = "servers:start"
      SERVERS_STOP = "servers:stop"
      SERVERS_DELETE = "servers:delete"
      SERVERS_MANAGE = "servers:manage"  # Admin: all servers
      
      # Resources
      RESOURCES_READ_OWN = "resources:read_own"
      RESOURCES_READ_ALL = "resources:read_all"
      
      # Environment/Plan management
      ENVIRONMENTS_MANAGE = "environments:manage"
      PLANS_MANAGE = "plans:manage"
      
      # Credit management
      CREDITS_READ = "credits:read"
      CREDITS_GRANT = "credits:grant"
      CREDITS_DEDUCT = "credits:deduct"
      
      # Audit
      AUDIT_READ = "audit:read"
      
      # Super admin wildcard
      ALL = "*"
  ```

- [ ] **Role-Permission Matrix** (`backend/app/core/roles.py`)
  ```python
  ROLE_PERMISSIONS = {
      "super_admin": [Permission.ALL],
      "admin": [
          Permission.USERS_READ, Permission.USERS_CREATE, 
          Permission.USERS_UPDATE, Permission.USERS_DELETE,
          Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE,
          Permission.RESOURCES_READ_ALL,
          Permission.ENVIRONMENTS_MANAGE, Permission.PLANS_MANAGE,
          Permission.CREDITS_READ, Permission.CREDITS_GRANT, Permission.CREDITS_DEDUCT,
          Permission.AUDIT_READ,
      ],
      "moderator": [
          Permission.USERS_READ, Permission.USERS_CREATE, Permission.USERS_UPDATE,
          Permission.SERVERS_READ_ALL, Permission.RESOURCES_READ_ALL,
      ],
      "support": [
          Permission.USERS_READ,
          Permission.SERVERS_READ_ALL, Permission.SERVERS_START, Permission.SERVERS_STOP,
          Permission.RESOURCES_READ_ALL,
      ],
      "user": [
          Permission.SERVERS_READ_OWN, Permission.SERVERS_START, 
          Permission.SERVERS_STOP, Permission.SERVERS_DELETE,
          Permission.RESOURCES_READ_OWN, Permission.CREDITS_READ,
      ],
      "guest": [
          Permission.SERVERS_READ_OWN,
      ],
  }
  ```

- [ ] **Permission Checking Functions**
  - `has_permission(user, permission)` — Check single permission
  - `has_any_permission(user, permissions)` — Check any of a list
  - `has_all_permissions(user, permissions)` — Check all in a list
  - `get_user_permissions(user)` — Get all permissions for a user

- [ ] **Permission Decorator** (`backend/app/dependencies.py`)
  ```python
  def require_permissions(*permissions):
      """Decorator to require specific permissions"""
      async def checker(current_user: User = Depends(get_current_user)):
          if not has_any_permission(current_user, permissions):
              raise HTTPException(status_code=403, detail="Insufficient permissions")
          return current_user
      return Depends(checker)
  ```

- [ ] **Ownership Checking**
  - `require_ownership(model, id_param)` — Generic ownership checker
  - `is_owner(user, resource)` — Check if user owns resource
  - `is_admin_or_owner(user, resource)` — Admin bypass

#### Database Tasks

- [ ] **Update roles table** — Use JSONB permissions array instead of hardcoded
- [ ] **Migration** — Alembic migration for permission structure

### Day 3-4: User CRUD API

#### Backend Tasks

- [ ] **Enhanced User Model** (update `backend/app/models/user.py`)
  - Add `phone`, `department`, `organization` to profile
  - Add `mfa_enabled`, `mfa_secret` to security
  - Add `disabled_at`, `disabled_by` for soft delete

- [ ] **User Service** (`backend/app/services/user_service.py`)
  - `create_user(data, actor)` — Create with audit logging
  - `get_user(user_id, requester)` — Get with permission check
  - `list_users(filters, pagination, requester)` — List with filtering
  - `update_user(user_id, data, requester)` — Update with validation
  - `delete_user(user_id, requester)` — Soft delete
  - `disable_user(user_id, requester)` — Disable account
  - `impersonate_user(user_id, requester)` — Super admin only

- [ ] **User API Endpoints** (`backend/app/api/users.py`)
  ```
  GET    /api/users              # List users (paginated, filterable)
         Query params:
         - role: Filter by role
         - status: active, disabled, pending
         - search: Search username/email/full_name
         - sort: created_at, last_login, credit_balance
         - page, limit: Pagination
  
  POST   /api/users              # Create user (admin/moderator)
         Body: {username, email, password, role, full_name, credits}
  
  GET    /api/users/{id}         # Get user details
  PUT    /api/users/{id}         # Update user
         Body: {full_name, email, role, profile, preferences}
  
  DELETE /api/users/{id}         # Delete user (admin only)
  
  POST   /api/users/{id}/disable # Disable/enable user
         Body: {reason, disabled}
  
  POST   /api/users/{id}/impersonate  # Impersonate (super_admin only)
         Returns: Temporary JWT for impersonated user
  
  GET    /api/users/{id}/servers      # Get user's servers
  GET    /api/users/{id}/resources    # Get user's resource usage
  GET    /api/users/{id}/credits      # Get user's credit history
  GET    /api/users/{id}/activity     # Get user's activity log
  ```

- [ ] **User List Response**
  ```json
  {
    "users": [
      {
        "id": "uuid",
        "username": "string",
        "email": "string",
        "full_name": "string",
        "role": "string",
        "credit_balance": 500,
        "is_active": true,
        "last_login": "2026-04-27T10:00:00Z",
        "created_at": "2026-04-27T10:00:00Z",
        "server_count": 2
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 150,
      "total_pages": 8
    }
  }
  ```

- [ ] **Bulk Operations**
  ```
  POST /api/users/bulk-disable
  POST /api/users/bulk-enable
  POST /api/users/bulk-delete
  POST /api/users/bulk-update-role
  ```

### Day 5-7: RBAC Enforcement

#### Backend Tasks

- [ ] **Apply Permissions to All Endpoints**
  - `GET /api/users` → `users:read`
  - `POST /api/users` → `users:create`
  - `PUT /api/users/{id}` → `users:update` (or own profile)
  - `DELETE /api/users/{id}` → `users:delete`
  - `GET /api/servers` → `servers:read_own` (own) or `servers:read_all` (admin)
  - `POST /api/servers` → `servers:start`
  - `POST /api/servers/{id}/stop` → `servers:stop` (own or admin)
  - `GET /api/tokens` → Own tokens only (always)

- [ ] **Ownership Middleware**
  ```python
  # Users can only access their own resources unless admin
  @router.get("/servers/{server_id}")
  async def get_server(
      server_id: str,
      current_user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db)
  ):
      server = await get_server_by_id(db, server_id)
      if not server:
          raise HTTPException(404, "Server not found")
      
      # Check ownership or admin permission
      if server.user_id != current_user.id and not has_permission(current_user, Permission.SERVERS_READ_ALL):
          raise HTTPException(403, "Access denied")
      
      return server
  ```

- [ ] **Permission Tests**
  - Test each role can access appropriate endpoints
  - Test cross-user access is blocked
  - Test admin bypass works
  - Test super_admin wildcard works

---

## Week 5: User Profile, Preferences & Credit System

### Day 1-2: User Profile & Settings

#### Backend Tasks

- [ ] **Profile API** (`backend/app/api/profile.py`)
  ```
  GET    /api/profile           # Get own profile
  PUT    /api/profile           # Update own profile
         Body: {full_name, email, phone, timezone, department, organization, avatar}
  
  PUT    /api/profile/password  # Change password
         Body: {current_password, new_password}
  
  GET    /api/profile/servers   # Get own servers
  GET    /api/profile/usage     # Get own resource usage
  GET    /api/profile/activity  # Get own activity timeline
  ```

- [ ] **Profile Validation**
  - Email uniqueness check
  - Password strength requirements
  - Username immutability
  - Avatar URL validation

#### Frontend Tasks

- [ ] **Profile Page** (`frontend/src/app/dashboard/profile/page.tsx`)
  - View profile information
  - Edit profile form
  - Change password form
  - Activity timeline
  - Server usage chart

- [ ] **Settings Layout**
  - Sidebar navigation for settings sections
  - Tabbed interface (Profile, Preferences, Security, Tokens)

### Day 3-4: User Preferences System

#### Backend Tasks

- [ ] **Preferences Schema** (stored in `users.preferences` JSONB)
  ```json
  {
    "theme": "dark|light|system",
    "language": "en|es|fr|de|ja|zh",
    "timezone": "UTC|America/New_York|Europe/London|...",
    "date_format": "ISO|US|EU",
    
    "default_environment": "dev|base|...",
    "default_plan": "nano|micro|small|...",
    "default_server_name_template": "{environment}-{date}",
    
    "notifications": {
      "email": {
        "server_events": true,
        "credit_low": true,
        "security_alerts": true,
        "marketing": false
      },
      "webhook": {
        "url": "https://hooks.slack.com/...",
        "events": ["server_start", "server_stop", "credit_low"]
      }
    },
    
    "dashboard": {
      "default_view": "grid|list",
      "show_inactive_servers": false,
      "auto_refresh_interval": 30
    },
    
    "editor": {
      "font_size": 14,
      "tab_size": 2,
      "word_wrap": true,
      "minimap": true
    }
  }
  ```

- [ ] **Preferences API** (`backend/app/api/preferences.py`)
  ```
  GET    /api/preferences              # Get all preferences
  PUT    /api/preferences              # Update preferences (partial)
  PUT    /api/preferences/{key}        # Update single preference
  DELETE /api/preferences              # Reset to defaults
  GET    /api/preferences/defaults     # Get default preferences
  ```

- [ ] **Preference Validation**
  - Type checking for each preference
  - Enum validation (theme, language, etc.)
  - Range validation (font_size: 8-32)
  - Webhook URL format validation

#### Frontend Tasks

- [ ] **Preferences Page** (`frontend/src/app/dashboard/settings/page.tsx`)
  - **Appearance Section**
    - Theme selector (Dark/Light/System)
    - Language selector
    - Timezone selector
    - Date format selector
  
  - **Defaults Section**
    - Default environment dropdown
    - Default plan dropdown
    - Server name template input
  
  - **Notifications Section**
    - Email notification toggles
    - Webhook URL input
    - Event selection checkboxes
  
  - **Dashboard Section**
    - Default view selector
    - Auto-refresh interval slider
    - Show inactive toggle

- [ ] **Quick Spawn with Defaults**
  - Dashboard "Quick Launch" button
  - Uses saved defaults
  - One-click server creation

### Day 5-7: Credit System

#### Database Tasks

- [ ] **Credit Ledger Table**
  ```sql
  CREATE TABLE credit_transactions (
      id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      amount INTEGER NOT NULL,  -- Positive = credit, Negative = debit
      balance_after INTEGER NOT NULL,
      type VARCHAR(50) NOT NULL,  -- daily_allowance, server_usage, admin_grant, purchase, refund
      description TEXT,
      server_id UUID REFERENCES servers(id),
      plan_id UUID,
      actor_id UUID,  -- Who initiated (NULL = system)
      metadata JSONB DEFAULT '{}',
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  
  CREATE INDEX idx_credit_transactions_user_id ON credit_transactions(user_id);
  CREATE INDEX idx_credit_transactions_type ON credit_transactions(type);
  CREATE INDEX idx_credit_transactions_created_at ON credit_transactions(created_at);
  ```

#### Backend Tasks

- [ ] **Credit Service** (`backend/app/services/credit_service.py`)
  ```python
  class CreditService:
      async def get_balance(self, user_id: UUID) -> int
      async def get_transaction_history(self, user_id: UUID, limit: int = 50) -> List[Transaction]
      async def grant_daily_allowance(self, user_id: UUID) -> Transaction
      async def consume_credits(self, user_id: UUID, amount: int, reason: str) -> Transaction
      async def grant_credits(self, user_id: UUID, amount: int, actor_id: UUID, reason: str) -> Transaction
      async def deduct_credits(self, user_id: UUID, amount: int, actor_id: UUID, reason: str) -> Transaction
      async def check_sufficient_credits(self, user_id: UUID, required: int) -> bool
      async def get_low_credit_users(self, threshold: int = 100) -> List[User]
  ```

- [ ] **Credit API** (`backend/app/api/credits.py`)
  ```
  GET    /api/credits                    # Get own balance
  GET    /api/credits/history            # Get transaction history
         Query: type, from_date, to_date, page, limit
  
  # Admin only
  GET    /api/credits/users/{id}         # Get user's balance
  GET    /api/credits/users/{id}/history # Get user's transactions
  POST   /api/credits/users/{id}/grant   # Grant credits
         Body: {amount, reason}
  POST   /api/credits/users/{id}/deduct  # Deduct credits
         Body: {amount, reason}
  ```

- [ ] **Daily Allowance System**
  - Celery beat task: Run daily at 00:00 UTC
  - Reset all users' daily allowance
  - Credit balance += daily_allowance
  - Transaction type: `daily_allowance`
  - Skip users with `is_active = false`

- [ ] **Credit Consumption**
  - Server spawn: Deduct hourly rate × estimated hours
  - Server running: Periodic deduction (every 15 min)
  - Auto-stop when credits depleted
  - Transaction type: `server_usage`

- [ ] **Low Credit Alerts**
  - Threshold: 20% of daily allowance
  - Alert methods: API response header, email, webhook
  - Auto-stop servers when credits = 0

#### Frontend Tasks

- [ ] **Credit Display**
  - Header credit balance badge
  - Color coding (green > 50%, yellow 20-50%, red < 20%)
  - Tooltip showing daily allowance

- [ ] **Credit History Page**
  - Transaction table with filters
  - Pagination
  - Export to CSV
  - Charts (balance over time, usage by type)

---

## Week 6: Admin Dashboard, Frontend Integration & Polish

### Day 1-2: Admin Dashboard Backend

#### Backend Tasks

- [ ] **Admin Stats API** (`backend/app/api/admin.py`)
  ```
  GET /api/admin/stats
  Returns:
  {
    "users": {
      "total": 150,
      "active": 140,
      "disabled": 10,
      "by_role": {"user": 130, "admin": 15, "moderator": 5}
    },
    "servers": {
      "total": 45,
      "running": 23,
      "stopped": 22,
      "by_environment": {"dev": 30, "base": 15}
    },
    "credits": {
      "total_granted_today": 75000,
      "total_consumed_today": 45000,
      "low_credit_users": 5
    },
    "system": {
      "cpu_usage": 45.2,
      "memory_usage": 62.1,
      "disk_usage": 38.5,
      "active_containers": 23
    }
  }
  ```

- [ ] **User Management API (Admin)**
  ```
  GET /api/admin/users          # All users with full details
  POST /api/admin/users         # Create user
  PUT /api/admin/users/{id}     # Update any user
  DELETE /api/admin/users/{id}  # Delete user
  
  POST /api/admin/users/bulk-action
  Body: {action: "disable|enable|delete", user_ids: []}
  ```

- [ ] **Server Management API (Admin)**
  ```
  GET /api/admin/servers        # All servers (not just own)
  POST /api/admin/servers/{id}/start
  POST /api/admin/servers/{id}/stop
  DELETE /api/admin/servers/{id}
  
  POST /api/admin/servers/bulk-action
  Body: {action: "start|stop|delete", server_ids: []}
  ```

- [ ] **Credit Management API (Admin)**
  ```
  GET /api/admin/credits/summary
  POST /api/admin/credits/grant-bulk
  Body: {user_ids: [], amount: 1000, reason: "Promotion"}
  ```

- [ ] **Activity Logs API**
  ```
  GET /api/admin/activity
  Query: user_id, action, from_date, to_date, page, limit
  
  GET /api/admin/activity/{user_id}
  User-specific activity
  ```

### Day 3-4: Admin Dashboard Frontend

#### Frontend Tasks

- [ ] **Dashboard Layout**
  - Admin sidebar (Users, Servers, Credits, Activity, Settings)
  - Role-based navigation (hide admin links for non-admins)
  - Breadcrumb navigation

- [ ] **Admin Overview Page** (`frontend/src/app/dashboard/admin/page.tsx`)
  - Stats cards (Users, Servers, Credits, System)
  - Recent activity feed
  - Quick action buttons
  - Charts (user growth, server usage, credit flow)

- [ ] **User Management Table**
  - Sortable columns
  - Filter by role, status
  - Search by username/email
  - Bulk actions checkbox
  - Action buttons (Edit, Disable, Delete, Impersonate)
  - Pagination

- [ ] **Server Management Table**
  - All servers across all users
  - Filter by status, environment
  - Bulk start/stop/delete
  - Real-time status indicators

- [ ] **Credit Management Panel**
  - Grant credits to single user
  - Bulk grant credits
  - Credit transaction viewer
  - Low credit alerts list

- [ ] **Activity Timeline**
  - Filter by user, action type
  - Date range picker
  - Export to CSV

### Day 5-6: Frontend Auth Integration

#### Frontend Tasks

- [ ] **Auth State Management** (Zustand store)
  ```typescript
  interface AuthState {
    user: User | null;
    token: string | null;
    isAuthenticated: boolean;
    isAdmin: boolean;
    login: (username: string, password: string) => Promise<void>;
    logout: () => void;
    refreshToken: () => Promise<void>;
  }
  ```

- [ ] **Login Flow**
  - Client-side form validation
  - API call to `/api/auth/login`
  - Store JWT in httpOnly cookie (via Next.js API route)
  - Redirect to dashboard on success
  - Error handling (invalid creds, server error)

- [ ] **Protected Routes**
  - Middleware: Check auth on `/dashboard/*`
  - Redirect to login if not authenticated
  - Redirect to dashboard if already logged in

- [ ] **Role-Based UI**
  - Hide admin links for non-admins
  - Show/hide action buttons based on permissions
  - Conditional rendering based on role

- [ ] **API Client**
  - Axios instance with auth header
  - Automatic token refresh
  - Error interceptors (401 → logout)
  - Request/response logging (dev only)

### Day 7: Testing & Polish

#### Testing Tasks

- [ ] **Backend Unit Tests**
  - Permission checking functions
  - User service methods
  - Credit calculations
  - Ownership middleware

- [ ] **Backend Integration Tests**
  - Auth flow (login, me, logout)
  - User CRUD with permissions
  - Server lifecycle with credits
  - Credit transactions

- [ ] **Frontend Tests**
  - Login form validation
  - Dashboard navigation
  - Table sorting/filtering
  - Form submissions

- [ ] **E2E Tests**
  - Admin creates user → user logs in
  - User spawns server → credits deducted
  - Admin grants credits → balance updated
  - Permission denied scenarios

#### Polish Tasks

- [ ] **Error Handling**
  - Consistent error responses
  - Frontend error boundaries
  - Toast notifications
  - Loading states

- [ ] **Loading States**
  - Skeleton screens for tables
  - Spinners for async actions
  - Optimistic updates

- [ ] **Validation**
  - Form validation (client + server)
  - Real-time validation feedback
  - Password strength indicator

---

## Database Schema Changes

### New Tables

```sql
-- Credit Transactions
CREATE TABLE credit_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    type VARCHAR(50) NOT NULL,
    description TEXT,
    server_id UUID REFERENCES servers(id),
    plan_id UUID,
    actor_id UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Activity Logs (Audit)
CREATE TABLE activity_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50) NOT NULL,  -- user, server, credit
    target_id UUID,
    details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Modified Tables

```sql
-- Add to users table
ALTER TABLE users ADD COLUMN disabled_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN disabled_by UUID REFERENCES users(id);
ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN mfa_secret VARCHAR(255);

-- Add to servers table
ALTER TABLE servers ADD COLUMN cost_per_hour INTEGER DEFAULT 0;
ALTER TABLE servers ADD COLUMN total_cost INTEGER DEFAULT 0;
```

---

## Frontend Architecture

### New Pages

```
frontend/src/app/
├── (dashboard)/
│   ├── layout.tsx              # Dashboard layout with sidebar
│   ├── page.tsx                # Dashboard home (role-based)
│   ├── profile/
│   │   └── page.tsx            # User profile
│   ├── settings/
│   │   └── page.tsx            # Preferences & settings
│   ├── servers/
│   │   └── page.tsx            # Server management
│   └── admin/
│       ├── page.tsx            # Admin overview
│       ├── users/
│       │   └── page.tsx        # User management
│       ├── servers/
│       │   └── page.tsx        # Server management (all)
│       ├── credits/
│       │   └── page.tsx        # Credit management
│       └── activity/
│           └── page.tsx        # Activity logs
```

### New Components

```
frontend/src/components/
├── auth/
│   ├── LoginForm.tsx
│   ├── ProtectedRoute.tsx
│   └── PermissionGate.tsx
├── users/
│   ├── UserTable.tsx
│   ├── UserForm.tsx
│   └── UserCard.tsx
├── servers/
│   ├── ServerTable.tsx
│   ├── ServerCard.tsx
│   └── ServerStatusBadge.tsx
├── credits/
│   ├── CreditBalance.tsx
│   ├── CreditHistory.tsx
│   └── CreditGrantForm.tsx
├── ui/
│   ├── DataTable.tsx          # Reusable sortable/filterable table
│   ├── Pagination.tsx
│   ├── SearchBar.tsx
│   ├── FilterDropdown.tsx
│   └── StatCard.tsx
└── layout/
    ├── Sidebar.tsx
    ├── Header.tsx
    └── Breadcrumb.tsx
```

### State Management

```typescript
// stores/authStore.ts
// stores/userStore.ts
// stores/serverStore.ts
// stores/creditStore.ts
// stores/preferenceStore.ts
```

---

## API Summary

### Authentication
```
POST   /api/auth/login
POST   /api/auth/logout
POST   /api/auth/refresh
GET    /api/auth/me
POST   /api/auth/oauth/callback
```

### Users
```
GET    /api/users
POST   /api/users
GET    /api/users/{id}
PUT    /api/users/{id}
DELETE /api/users/{id}
POST   /api/users/{id}/disable
POST   /api/users/{id}/impersonate
GET    /api/users/{id}/servers
GET    /api/users/{id}/resources
GET    /api/users/{id}/credits
GET    /api/users/{id}/activity
POST   /api/users/bulk-disable
POST   /api/users/bulk-enable
POST   /api/users/bulk-delete
POST   /api/users/bulk-update-role
```

### Profile
```
GET    /api/profile
PUT    /api/profile
PUT    /api/profile/password
GET    /api/profile/servers
GET    /api/profile/usage
GET    /api/profile/activity
```

### Preferences
```
GET    /api/preferences
PUT    /api/preferences
PUT    /api/preferences/{key}
DELETE /api/preferences
GET    /api/preferences/defaults
```

### Credits
```
GET    /api/credits
GET    /api/credits/history
GET    /api/credits/users/{id}
GET    /api/credits/users/{id}/history
POST   /api/credits/users/{id}/grant
POST   /api/credits/users/{id}/deduct
```

### Tokens (from Phase 1)
```
GET    /api/tokens
POST   /api/tokens
GET    /api/tokens/{id}
DELETE /api/tokens/{id}
POST   /api/tokens/{id}/regenerate
GET    /api/tokens/{id}/usage
```

### Admin
```
GET    /api/admin/stats
GET    /api/admin/users
GET    /api/admin/servers
GET    /api/admin/credits/summary
GET    /api/admin/activity
POST   /api/admin/users/bulk-action
POST   /api/admin/servers/bulk-action
POST   /api/admin/credits/grant-bulk
```

### Servers (enhanced)
```
GET    /api/servers
POST   /api/servers
GET    /api/servers/{id}
POST   /api/servers/{id}/start    # Now implemented
POST   /api/servers/{id}/stop
POST   /api/servers/{id}/restart  # New
DELETE /api/servers/{id}
GET    /api/servers/{id}/logs     # New
```

---

## Testing Strategy

### Unit Tests (Backend)

```
backend/tests/
├── unit/
│   ├── test_permissions.py
│   ├── test_user_service.py
│   ├── test_credit_service.py
│   └── test_ownership.py
```

### Integration Tests (Backend)

```
backend/tests/
├── integration/
│   ├── test_auth_flow.py
│   ├── test_user_crud.py
│   ├── test_server_lifecycle.py
│   ├── test_credit_system.py
│   └── test_rbac.py
```

### Frontend Tests

```
frontend/src/
├── __tests__/
│   ├── components/
│   │   ├── LoginForm.test.tsx
│   │   ├── UserTable.test.tsx
│   │   └── CreditBalance.test.tsx
│   └── pages/
│       ├── dashboard.test.tsx
│       └── admin.test.tsx
```

### E2E Tests

```
e2e/
├── auth.spec.ts
├── user-management.spec.ts
├── server-lifecycle.spec.ts
└── credit-system.spec.ts
```

---

## Celery Tasks

```python
# app/tasks/credit_tasks.py

@app.task
def reset_daily_credits():
    """Grant daily allowance to all active users"""
    pass

@app.task
def deduct_server_usage():
    """Deduct credits for running servers"""
    pass

@app.task
def check_low_credit_users():
    """Find users with low credits and send alerts"""
    pass

@app.task
def auto_stop_zero_credit_servers():
    """Stop servers for users with 0 credits"""
    pass

# app/tasks/audit_tasks.py

@app.task
def log_activity(actor_id, action, target_type, target_id, details):
    """Log user activity asynchronously"""
    pass
```

---

## Deliverables

By end of Phase 2, the following should be functional:

### Backend
- [ ] Granular RBAC with permission checking
- [ ] Complete user CRUD with admin controls
- [ ] User profile and preferences system
- [ ] Credit system with daily allowance and consumption
- [ ] Admin dashboard APIs
- [ ] Activity logging
- [ ] Comprehensive test coverage (>80%)

### Frontend
- [ ] Working login flow with JWT
- [ ] Protected routes
- [ ] User profile and settings pages
- [ ] Admin dashboard with user/server/credit management
- [ ] Role-based navigation and UI
- [ ] Responsive design

### Infrastructure
- [ ] Celery tasks for credit management
- [ ] Database migrations
- [ ] Updated API documentation

---

## Success Criteria

```gherkin
Given I am an admin
When I create a new user with role "moderator"
Then the user can log in
And the user receives 500 daily credits
And the user can create other users
But the user cannot access other users' servers

Given I am a regular user
When I try to access admin dashboard
Then I get a 403 Forbidden error

Given I have 20 credits remaining
When I try to start a server costing 40 credits/hour
Then I get an error: "Insufficient credits"

Given I am a user with no servers
When I set my default environment to "dev" in preferences
And I click "Quick Spawn"
Then a dev server starts with my saved defaults

Given I am an admin
When I view the admin dashboard
Then I see all users, servers, and credit statistics
And I can grant 1000 credits to a user
And the user's balance updates immediately
```

---

## Risk Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Permission system too complex | Medium | Medium | Start with simple matrix, iterate |
| Credit race conditions | High | Low | Use database transactions, optimistic locking |
| Frontend auth complexity | Medium | Medium | Use proven patterns (httpOnly cookies) |
| Admin dashboard performance | Medium | Medium | Pagination, caching, lazy loading |
| Daily credit reset failures | High | Low | Idempotent tasks, retry logic, monitoring |

---

## Dependencies

- Phase 1 completion (infrastructure, basic auth, server spawning)
- shadcn/ui components installed
- Zustand for state management
- Recharts for charts
- React Query for data fetching

---

**Next**: Phase 3 — Environment Templates & Resource Management (Weeks 7-9)
