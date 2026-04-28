# Phase 3: Environment Templates & Resource Management

**Goal**: Multiple environments, resource quotas, and limits
**Timeline**: Weeks 7-9
**Status**: In Progress

---

## Environment Template System

### Database Schema

**environment_templates table:**
- id: UUID PK
- name: string (unique)
- slug: string (unique, URL-friendly)
- description: text
- image: string (Docker image name)
- dockerfile: text (optional, for custom builds)
- packages: JSONB (list of packages to install)
- environment_variables: JSONB (env vars to set)
- volumes: JSONB (mount points)
- ports: JSONB (exposed ports)
- icon: string (emoji or icon name)
- color: string (brand color hex)
- category: string (neutronics, multiphysics, visualization, base, dev)
- is_active: boolean
- is_public: boolean
- created_by: UUID FK → users
- created_at: datetime
- updated_at: datetime

### API Endpoints

- `GET /api/environments` - List environments (public + user's org)
- `GET /api/environments/{id}` - Get environment details
- `POST /api/environments` - Create environment (admin)
- `PUT /api/environments/{id}` - Update environment (admin)
- `DELETE /api/environments/{id}` - Deactivate environment (admin)
- `POST /api/environments/{id}/activate` - Activate environment (admin)
- `POST /api/environments/{id}/clone` - Clone environment (admin)

### Frontend

- Environment builder page (/dashboard/admin/environments)
- Environment cards with icon, color, category
- Dockerfile editor (textarea with syntax highlighting)
- Package manager (add/remove packages)
- Environment variable editor (key-value pairs)
- Volume mount configuration
- Port configuration
- Preview card showing branding

---

## Server Plans

### Database Schema

**server_plans table:**
- id: UUID PK
- name: string (unique)
- slug: string (unique)
- description: text
- category: string (cpu, gpu)
- cpu_limit: float (cores)
- memory_limit: string (e.g., "4g")
- disk_limit: string (e.g., "20g")
- gpu_limit: int (0 for CPU plans)
- max_servers_per_user: int
- cost_per_hour: int (credits)
- cooldown_seconds: int (between spawns)
- requires_approval: boolean
- allowed_roles: JSONB (roles that can use this plan)
- is_active: boolean
- priority: int (scheduling priority, higher = better)
- created_at: datetime
- updated_at: datetime

### API Endpoints

- `GET /api/plans` - List plans (filtered by user's role)
- `GET /api/plans/{id}` - Get plan details
- `POST /api/plans` - Create plan (admin)
- `PUT /api/plans/{id}` - Update plan (admin)
- `DELETE /api/plans/{id}` - Deactivate plan (admin)

### Frontend

- Plan builder page (/dashboard/admin/plans)
- Resource sliders (CPU, memory, disk)
- Cost calculator (per hour, per day)
- Role restriction selector
- Priority setting
- Plan cards with specs

---

## Resource Quotas

### Database Schema

**resource_quotas table:**
- id: UUID PK
- user_id: UUID FK (nullable, for per-user quotas)
- role: string (nullable, for per-role quotas)
- plan_id: UUID FK (nullable, for per-plan quotas)
- max_cpu_total: float (max across all servers)
- max_memory_total: string
- max_disk_total: string
- max_gpu_total: int
- max_servers_total: int
- usage_cpu: float (current usage)
- usage_memory: string
- usage_disk: string
- usage_gpu: int
- usage_servers: int
- created_at: datetime
- updated_at: datetime

### API Endpoints

- `GET /api/quotas` - Get current user's quotas
- `GET /api/quotas/{user_id}` - Get specific user's quotas (admin)
- `PUT /api/quotas/{user_id}` - Update user's quotas (admin)
- `GET /api/quotas/check` - Check if spawn is allowed

### Enforcement

- Check before spawn: CPU, memory, disk, GPU, server count
- Update on spawn: increment usage
- Update on stop: decrement usage
- Alert when approaching limit

---

## Resource Limits

### Docker Integration

When spawning container:
- `--cpus={plan.cpu_limit}`
- `--memory={plan.memory_limit}`
- `--storage-opt size={plan.disk_limit}`
- `--gpus={plan.gpu_limit}` (if GPU plan)
- `--shm-size=1g` (shared memory for scientific computing)

### Admin Overrides

- Admins can spawn with any plan regardless of quota
- Admin can override limits for specific containers
- Override logged in activity log

---

## Hardware Resource Scheduling

### Global Resource Pool

Track available resources across all hosts:
- total_cpu: 38 (32 main + 6 VPS)
- total_memory: "68g"
- total_disk: "1.1t"
- total_gpu: 0 (none available currently)

### Resource Availability Check

Before spawn:
1. Check user's quota
2. Check global pool availability
3. Check queue position (if resources unavailable)

### Queue System

**server_queue table:**
- id: UUID PK
- user_id: UUID FK
- environment_id: UUID FK
- plan_id: UUID FK
- status: string (pending, scheduled, failed)
- priority: int
- requested_at: datetime
- scheduled_at: datetime (nullable)
- started_at: datetime (nullable)
- error_message: text (nullable)

### Priority-Based Scheduling

- Priority = plan.priority + user.role_priority
- Higher priority users/plans scheduled first
- FIFO within same priority

### Auto-Stop Idle Servers

- Check last_activity timestamp
- Stop servers idle > 30 minutes (configurable)
- Notify user before stopping
- Free up resources for queue

---

## Volume Management

### Persistent User Volumes

- Created on first spawn
- Named: `nukelab-user-{user_id}`
- Mounted at `/home/user/workspace`
- Survives container restarts

### Shared Workspace Volumes

- Named: `nukelab-shared-{workspace_id}`
- Mount options: ro (read-only), rw (read-write)
- Permission management

### Volume Backup/Restore

- Scheduled backups via Celery
- Backup to S3-compatible storage
- Point-in-time restore

---

## Environment Images

### Build System

- Dockerfile stored in environment_templates
- Build triggered on environment creation/update
- Build logs stored
- Multi-stage builds for optimization

### Image Registry

- Local registry: registry:5000
- Image naming: `nukelab/{environment_slug}:{version}`
- Versioning: semantic versioning

### Base Image Updates

- Base images: ubuntu:22.04, nvidia/cuda:12.0-base
- Update base images via admin action
- Rebuild all environments with new base

---

## Deliverables

- [ ] Multiple environments available (dev, neutronics, multiphysics, visualization, base)
- [ ] Multiple plans available (nano, micro, small, medium, large, xlarge)
- [ ] Users can choose environment AND plan when spawning
- [ ] Resource quotas enforced per plan
- [ ] Admin can create/modify environments and plans
- [ ] Queue system for resource scheduling
- [ ] Auto-stop idle servers
- [ ] Volume management

---

## Success Criteria

```gherkin
Given I am a user
When I spawn a server with "neutronics" environment and "small" plan
Then the container has OpenMC and DAGMC installed
And the container has 2 CPU and 4GB RAM allocated

Given I am a user
When I spawn a server with "neutronics" environment and "large" plan
Then the container has OpenMC and DAGMC installed
And the container has 8 CPU and 16GB RAM allocated

Given I have reached my server limit for "small" plan (max_per_user=3)
When I try to spawn a 4th "small" server
Then I get an error: "Plan limit reached for small"
```

---

## Files

- `/backend/app/models/environment_template.py`
- `/backend/app/models/server_plan.py`
- `/backend/app/models/resource_quota.py`
- `/backend/app/models/server_queue.py`
- `/backend/app/api/environments.py`
- `/backend/app/api/plans.py`
- `/backend/app/api/quotas.py`
- `/backend/app/services/environment_service.py`
- `/backend/app/services/plan_service.py`
- `/backend/app/services/quota_service.py`
- `/backend/app/services/scheduler_service.py`
- `/frontend/src/app/dashboard/admin/environments/page.tsx`
- `/frontend/src/app/dashboard/admin/plans/page.tsx`
- `/frontend/src/components/environments/EnvironmentBuilder.tsx`
- `/frontend/src/components/plans/PlanBuilder.tsx`
