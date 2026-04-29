# Phase 4: Real-Time Monitoring Dashboard

**Duration**: Weeks 10-12  
**Goal**: Live resource monitoring, historical data, alerting, and health checks  
**Status**: 📝 PLANNED  
**Previous Phase**: [Phase 3: Environment Templates & Resource Management](../03-environment-resource-management/PLAN.md)

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Database Schema](#database-schema)
5. [Backend Implementation](#backend-implementation)
6. [Frontend Implementation](#frontend-implementation)
7. [API Design](#api-design)
8. [Testing Strategy](#testing-strategy)
9. [Week-by-Week Breakdown](#week-by-week-breakdown)
10. [Deliverables](#deliverables)
11. [Success Criteria](#success-criteria)
12. [Risk Mitigation](#risk-mitigation)
13. [Dependencies](#dependencies)

---

## Overview

Phase 4 adds real-time observability to the NukeLab platform. It provides:

- **Live Metrics**: CPU, memory, disk, network usage per container streamed in real-time
- **Historical Data**: Time-series storage of metrics for trend analysis (7d/30d/90d)
- **Alerting System**: Configurable rules for quota thresholds, container crashes, resource exhaustion
- **Health Checks**: Container health probes, auto-restart on failure, system health dashboard
- **Dashboard**: Admin global view + per-user resource usage with interactive charts

### What Makes This Phase Complex

1. **Dual Data Flow**: REST for historical queries + WebSocket for real-time streaming
2. **High-Frequency Collection**: Docker Stats API streams every 1-5 seconds per container
3. **Time-Series Storage**: Efficient PostgreSQL partitioning for high-volume metrics
4. **Connection Management**: WebSocket lifecycle (connect, subscribe, reconnect, cleanup)
5. **Alert Evaluation**: Continuous rule evaluation without blocking metric collection

---

## Prerequisites

### From Phase 1-3
- [x] Docker/Podman socket access for container stats
- [x] PostgreSQL with JSONB support
- [x] Redis for pub/sub
- [x] FastAPI with async endpoints
- [x] Celery workers for background tasks
- [x] Server lifecycle (spawn/start/stop/delete) working
- [x] RBAC system with permission checks
- [x] WebSocket support in FastAPI (native, built-in)

### New Dependencies

```
# Backend
aiodocker==0.24.0          # Already installed — Docker Stats API streaming
python-socketio==5.11.0    # Socket.IO for WebSocket (better than raw WS)
psutil==5.9.8              # Host-level system metrics (CPU, RAM, disk)
numpy==1.26.0              # Metrics aggregation/computation

# Frontend
recharts==2.12.0           # Already installed — charts
ws==8.16.0                 # WebSocket client (or native browser WS)
```

---

## Architecture

### High-Level Flow

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  Docker Daemon  │◄────►│  Metrics         │◄────►│  PostgreSQL     │
│  (Container     │      │  Collector       │      │  (Time-Series   │
│   Stats API)    │      │  (Celery Task)   │      │   Metrics)      │
└─────────────────┘      └────────┬─────────┘      └─────────────────┘
                                  │
                                  ▼
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  Redis Pub/Sub  │◄────►│  Metrics         │◄────►│  WebSocket      │
│  (Broadcast)    │      │  Manager         │      │  Server         │
└─────────────────┘      └──────────────────┘      └────────┬────────┘
                                                             │
                          ┌──────────────────────────────────┼──────────────────┐
                          │                                  │                  │
                          ▼                                  ▼                  ▼
                   ┌─────────────┐                   ┌──────────────┐    ┌──────────────┐
                   │  Admin      │                   │  User        │    │  Alert       │
                   │  Dashboard  │                   │  Dashboard   │    │  Manager     │
                   │  (Global)   │                   │  (Own Usage) │    │              │
                   └─────────────┘                   └──────────────┘    └──────────────┘
```

### Component Responsibilities

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Metrics Collector** | Celery Beat + aiodocker | Poll Docker Stats API every 5s per running container |
| **Metrics Manager** | FastAPI service | Aggregate, normalize, persist metrics; handle queries |
| **WebSocket Server** | python-socketio | Stream real-time metrics to subscribed clients |
| **Redis Pub/Sub** | Redis | Broadcast metrics from collector to WebSocket server |
| **Alert Manager** | Celery task | Evaluate rules, trigger notifications |
| **Metrics Storage** | PostgreSQL + partitioning | Time-series data with BRIN indexes |

### Data Flow

```
1. COLLECT (every 5 seconds)
   Docker Stats API → Metrics Collector → Redis Pub/Sub
                                         → PostgreSQL (persist)

2. STREAM (real-time)
   Redis Pub/Sub → WebSocket Server → Client (admin/user dashboard)

3. QUERY (on-demand)
   Client → REST API → PostgreSQL → Aggregated response

4. ALERT (continuous)
   Metrics Collector → Alert Rules Engine → Notifications (email/in-app)
```

---

## Database Schema

### New Tables

#### `server_metrics` — Time-series container metrics

```sql
CREATE TABLE server_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    container_id VARCHAR(255) NOT NULL,
    
    -- CPU metrics
    cpu_percent FLOAT,
    cpu_usage_ns BIGINT,           -- Docker cgroup CPU usage in nanoseconds
    cpu_system_ns BIGINT,          -- System CPU time in nanoseconds
    cpu_cores INT,                 -- Number of CPU cores allocated
    
    -- Memory metrics
    memory_used BIGINT,            -- Bytes
    memory_total BIGINT,           -- Bytes
    memory_percent FLOAT,
    memory_cache BIGINT,
    memory_swap_used BIGINT,
    
    -- Disk metrics
    disk_read_bytes BIGINT,
    disk_write_bytes BIGINT,
    disk_read_iops INT,
    disk_write_iops INT,
    
    -- Network metrics
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT,
    network_rx_packets BIGINT,
    network_tx_packets BIGINT,
    network_rx_errors INT,
    network_tx_errors INT,
    
    -- GPU metrics (nullable)
    gpu_percent FLOAT,
    gpu_memory_used BIGINT,
    gpu_memory_total BIGINT,
    gpu_temperature FLOAT,
    
    -- Process metrics
    pids INT,                      -- Number of processes
    
    -- Metadata
    collected_at TIMESTAMPTZ NOT NULL,
    
    -- Partitioning
    -- Monthly partitions for efficient retention
) PARTITION BY RANGE (collected_at);

-- Create monthly partitions (automated by script)
CREATE TABLE server_metrics_2026_04 PARTITION OF server_metrics
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE server_metrics_2026_05 PARTITION OF server_metrics
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

-- BRIN index for time-series (very efficient for ordered data)
CREATE INDEX idx_server_metrics_brin ON server_metrics USING BRIN (collected_at);
CREATE INDEX idx_server_metrics_server_id ON server_metrics (server_id, collected_at DESC);
```

#### `system_metrics` — Host-level system metrics

```sql
CREATE TABLE system_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host VARCHAR(255) NOT NULL DEFAULT 'localhost',
    
    -- CPU
    cpu_percent FLOAT,
    cpu_count INT,
    cpu_load_1m FLOAT,
    cpu_load_5m FLOAT,
    cpu_load_15m FLOAT,
    
    -- Memory
    memory_used BIGINT,
    memory_total BIGINT,
    memory_percent FLOAT,
    memory_available BIGINT,
    
    -- Disk
    disk_used BIGINT,
    disk_total BIGINT,
    disk_percent FLOAT,
    disk_read_bytes BIGINT,
    disk_write_bytes BIGINT,
    
    -- Network
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT,
    
    -- Docker
    docker_containers_running INT,
    docker_containers_total INT,
    docker_images_total INT,
    
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (collected_at);

CREATE INDEX idx_system_metrics_brin ON system_metrics USING BRIN (collected_at);
CREATE INDEX idx_system_metrics_host ON system_metrics (host, collected_at DESC);
```

#### `alert_rules` — Configurable alert rules

```sql
CREATE TABLE alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- What to monitor
    metric_type VARCHAR(50) NOT NULL,  -- cpu, memory, disk, gpu, pids, container_health
    
    -- Condition
    operator VARCHAR(10) NOT NULL,     -- >, <, >=, <=, ==, !=
    threshold FLOAT NOT NULL,
    
    -- Scope
    scope VARCHAR(50) NOT NULL DEFAULT 'global',  -- global, user, server, plan
    target_id UUID,                  -- If scope is user/server/plan
    
    -- Timing
    duration_seconds INT DEFAULT 60,  -- Must breach for this long before alerting
    cooldown_seconds INT DEFAULT 300, -- Minimum time between alerts
    
    -- Notifications
    notify_admin BOOLEAN DEFAULT true,
    notify_user BOOLEAN DEFAULT true,
    email_enabled BOOLEAN DEFAULT false,
    webhook_url TEXT,
    
    -- State
    is_active BOOLEAN DEFAULT true,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alert_rules_active ON alert_rules (is_active, scope);
```

#### `alert_history` — Fired alerts log

```sql
CREATE TABLE alert_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID REFERENCES alert_rules(id),
    
    -- What triggered it
    server_id UUID REFERENCES servers(id),
    user_id UUID REFERENCES users(id),
    metric_value FLOAT NOT NULL,
    threshold FLOAT NOT NULL,
    
    -- Status
    status VARCHAR(50) DEFAULT 'fired',  -- fired, acknowledged, resolved, suppressed
    
    -- Notifications sent
    admin_notified BOOLEAN DEFAULT false,
    user_notified BOOLEAN DEFAULT false,
    email_sent BOOLEAN DEFAULT false,
    webhook_sent BOOLEAN DEFAULT false,
    
    -- Acknowledgment
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    notes TEXT,
    
    -- Resolution
    resolved_at TIMESTAMPTZ,
    resolved_value FLOAT,
    
    fired_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alert_history_status ON alert_history (status, fired_at DESC);
CREATE INDEX idx_alert_history_user ON alert_history (user_id, fired_at DESC);
CREATE INDEX idx_alert_history_server ON alert_history (server_id, fired_at DESC);
```

#### `health_checks` — Container health check results

```sql
CREATE TABLE health_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    container_id VARCHAR(255) NOT NULL,
    
    -- Check result
    status VARCHAR(50) NOT NULL,  -- healthy, unhealthy, starting, unknown
    exit_code INT,
    output TEXT,
    
    -- Failure tracking
    consecutive_failures INT DEFAULT 0,
    last_success_at TIMESTAMPTZ,
    
    checked_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_health_checks_server ON health_checks (server_id, checked_at DESC);
CREATE INDEX idx_health_checks_status ON health_checks (status, checked_at DESC);
```

### Schema Migration

File: `backend/alembic/versions/004_add_monitoring_schema.py`

```python
def upgrade():
    # Create server_metrics table with partitioning
    op.execute("""
        CREATE TABLE server_metrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            container_id VARCHAR(255) NOT NULL,
            cpu_percent FLOAT,
            cpu_usage_ns BIGINT,
            cpu_system_ns BIGINT,
            cpu_cores INT,
            memory_used BIGINT,
            memory_total BIGINT,
            memory_percent FLOAT,
            memory_cache BIGINT,
            memory_swap_used BIGINT,
            disk_read_bytes BIGINT,
            disk_write_bytes BIGINT,
            disk_read_iops INT,
            disk_write_iops INT,
            network_rx_bytes BIGINT,
            network_tx_bytes BIGINT,
            network_rx_packets BIGINT,
            network_tx_packets BIGINT,
            network_rx_errors INT,
            network_tx_errors INT,
            gpu_percent FLOAT,
            gpu_memory_used BIGINT,
            gpu_memory_total BIGINT,
            gpu_temperature FLOAT,
            pids INT,
            collected_at TIMESTAMPTZ NOT NULL
        ) PARTITION BY RANGE (collected_at);
    """)
    
    # Create initial partitions
    op.execute("CREATE TABLE server_metrics_2026_04 PARTITION OF server_metrics FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');")
    op.execute("CREATE TABLE server_metrics_2026_05 PARTITION OF server_metrics FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');")
    
    # Create indexes
    op.execute("CREATE INDEX idx_server_metrics_brin ON server_metrics USING BRIN (collected_at);")
    op.execute("CREATE INDEX idx_server_metrics_server_id ON server_metrics (server_id, collected_at DESC);")
    
    # Create system_metrics
    op.execute("""
        CREATE TABLE system_metrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            host VARCHAR(255) NOT NULL DEFAULT 'localhost',
            cpu_percent FLOAT,
            cpu_count INT,
            cpu_load_1m FLOAT,
            cpu_load_5m FLOAT,
            cpu_load_15m FLOAT,
            memory_used BIGINT,
            memory_total BIGINT,
            memory_percent FLOAT,
            memory_available BIGINT,
            disk_used BIGINT,
            disk_total BIGINT,
            disk_percent FLOAT,
            disk_read_bytes BIGINT,
            disk_write_bytes BIGINT,
            network_rx_bytes BIGINT,
            network_tx_bytes BIGINT,
            docker_containers_running INT,
            docker_containers_total INT,
            docker_images_total INT,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        ) PARTITION BY RANGE (collected_at);
    """)
    
    op.execute("CREATE TABLE system_metrics_2026_04 PARTITION OF system_metrics FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');")
    op.execute("CREATE TABLE system_metrics_2026_05 PARTITION OF system_metrics FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');")
    op.execute("CREATE INDEX idx_system_metrics_brin ON system_metrics USING BRIN (collected_at);")
    op.execute("CREATE INDEX idx_system_metrics_host ON system_metrics (host, collected_at DESC);")
    
    # Create alert_rules
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metric_type', sa.String(50), nullable=False),
        sa.Column('operator', sa.String(10), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('scope', sa.String(50), nullable=False, server_default='global'),
        sa.Column('target_id', sa.UUID(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('cooldown_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('notify_admin', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notify_user', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('webhook_url', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['target_id'], ['servers.id']),
    )
    op.create_index('idx_alert_rules_active', 'alert_rules', ['is_active', 'scope'])
    
    # Create alert_history
    op.create_table(
        'alert_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=True),
        sa.Column('server_id', sa.UUID(), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('metric_value', sa.Float(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='fired'),
        sa.Column('admin_notified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('user_notified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('email_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('webhook_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('acknowledged_by', sa.UUID(), nullable=True),
        sa.Column('acknowledged_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('resolved_value', sa.Float(), nullable=True),
        sa.Column('fired_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id']),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id']),
    )
    op.create_index('idx_alert_history_status', 'alert_history', ['status', 'fired_at DESC'])
    op.create_index('idx_alert_history_user', 'alert_history', ['user_id', 'fired_at DESC'])
    op.create_index('idx_alert_history_server', 'alert_history', ['server_id', 'fired_at DESC'])
    
    # Create health_checks
    op.create_table(
        'health_checks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('server_id', sa.UUID(), nullable=False),
        sa.Column('container_id', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('output', sa.Text(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_success_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('checked_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_health_checks_server', 'health_checks', ['server_id', 'checked_at DESC'])
    op.create_index('idx_health_checks_status', 'health_checks', ['status', 'checked_at DESC'])


def downgrade():
    op.drop_table('health_checks')
    op.drop_table('alert_history')
    op.drop_table('alert_rules')
    op.execute("DROP TABLE system_metrics;")
    op.execute("DROP TABLE server_metrics;")
```

---

## Backend Implementation

### 1. Models

#### `backend/app/models/server_metric.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class ServerMetric(Base):
    __tablename__ = "server_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    container_id = Column(String(255), nullable=False)
    
    # CPU
    cpu_percent = Column(Float)
    cpu_usage_ns = Column(BigInteger)
    cpu_system_ns = Column(BigInteger)
    cpu_cores = Column(Integer)
    
    # Memory
    memory_used = Column(BigInteger)
    memory_total = Column(BigInteger)
    memory_percent = Column(Float)
    memory_cache = Column(BigInteger)
    memory_swap_used = Column(BigInteger)
    
    # Disk
    disk_read_bytes = Column(BigInteger)
    disk_write_bytes = Column(BigInteger)
    disk_read_iops = Column(Integer)
    disk_write_iops = Column(Integer)
    
    # Network
    network_rx_bytes = Column(BigInteger)
    network_tx_bytes = Column(BigInteger)
    network_rx_packets = Column(BigInteger)
    network_tx_packets = Column(BigInteger)
    network_rx_errors = Column(Integer)
    network_tx_errors = Column(Integer)
    
    # GPU
    gpu_percent = Column(Float)
    gpu_memory_used = Column(BigInteger)
    gpu_memory_total = Column(BigInteger)
    gpu_temperature = Column(Float)
    
    # Process
    pids = Column(Integer)
    
    # Timestamp
    collected_at = Column(DateTime, nullable=False)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "server_id": str(self.server_id),
            "container_id": self.container_id,
            "cpu": {
                "percent": self.cpu_percent,
                "cores": self.cpu_cores,
            },
            "memory": {
                "used": self.memory_used,
                "total": self.memory_total,
                "percent": self.memory_percent,
            },
            "disk": {
                "read_bytes": self.disk_read_bytes,
                "write_bytes": self.disk_write_bytes,
            },
            "network": {
                "rx_bytes": self.network_rx_bytes,
                "tx_bytes": self.network_tx_bytes,
            },
            "gpu": {
                "percent": self.gpu_percent,
                "memory_used": self.gpu_memory_used,
                "temperature": self.gpu_temperature,
            } if self.gpu_percent else None,
            "pids": self.pids,
            "collected_at": self.collected_at.isoformat(),
        }
```

#### `backend/app/models/system_metric.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class SystemMetric(Base):
    __tablename__ = "system_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host = Column(String(255), nullable=False, default="localhost")
    
    # CPU
    cpu_percent = Column(Float)
    cpu_count = Column(Integer)
    cpu_load_1m = Column(Float)
    cpu_load_5m = Column(Float)
    cpu_load_15m = Column(Float)
    
    # Memory
    memory_used = Column(BigInteger)
    memory_total = Column(BigInteger)
    memory_percent = Column(Float)
    memory_available = Column(BigInteger)
    
    # Disk
    disk_used = Column(BigInteger)
    disk_total = Column(BigInteger)
    disk_percent = Column(Float)
    disk_read_bytes = Column(BigInteger)
    disk_write_bytes = Column(BigInteger)
    
    # Network
    network_rx_bytes = Column(BigInteger)
    network_tx_bytes = Column(BigInteger)
    
    # Docker
    docker_containers_running = Column(Integer)
    docker_containers_total = Column(Integer)
    docker_images_total = Column(Integer)
    
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

#### `backend/app/models/alert_rule.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class AlertRule(Base):
    __tablename__ = "alert_rules"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    metric_type = Column(String(50), nullable=False)  # cpu, memory, disk, gpu, pids
    operator = Column(String(10), nullable=False)     # >, <, >=, <=, ==, !=
    threshold = Column(Float, nullable=False)
    
    scope = Column(String(50), nullable=False, default="global")  # global, user, server, plan
    target_id = Column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=True)
    
    duration_seconds = Column(Integer, nullable=False, default=60)
    cooldown_seconds = Column(Integer, nullable=False, default=300)
    
    notify_admin = Column(Boolean, default=True)
    notify_user = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=False)
    webhook_url = Column(Text)
    
    is_active = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def evaluate(self, value: float) -> bool:
        """Evaluate if the metric value triggers this rule"""
        ops = {
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            ">=": lambda x, y: x >= y,
            "<=": lambda x, y: x <= y,
            "==": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
        }
        return ops.get(self.operator, lambda x, y: False)(value, self.threshold)
```

#### `backend/app/models/alert_history.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class AlertHistory(Base):
    __tablename__ = "alert_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id"))
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    
    metric_value = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    
    status = Column(String(50), default="fired")  # fired, acknowledged, resolved
    
    admin_notified = Column(Boolean, default=False)
    user_notified = Column(Boolean, default=False)
    email_sent = Column(Boolean, default=False)
    webhook_sent = Column(Boolean, default=False)
    
    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    acknowledged_at = Column(DateTime)
    notes = Column(Text)
    
    resolved_at = Column(DateTime)
    resolved_value = Column(Float)
    
    fired_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "rule_id": str(self.rule_id),
            "server_id": str(self.server_id),
            "user_id": str(self.user_id),
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "status": self.status,
            "acknowledged": self.acknowledged_at is not None,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
```

#### `backend/app/models/health_check.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class HealthCheck(Base):
    __tablename__ = "health_checks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    container_id = Column(String(255), nullable=False)
    
    status = Column(String(50), nullable=False)  # healthy, unhealthy, starting, unknown
    exit_code = Column(Integer)
    output = Column(Text)
    
    consecutive_failures = Column(Integer, default=0)
    last_success_at = Column(DateTime)
    
    checked_at = Column(DateTime, default=datetime.utcnow)
```

### 2. Services

#### `backend/app/services/metrics_collector.py` — Docker Stats Collection

```python
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
import aiodocker
from app.docker.client import get_docker_client
from app.db.session import get_db
from app.models.server import Server
from app.models.server_metric import ServerMetric
from sqlalchemy import select
import redis.asyncio as redis
from app.config import settings

class MetricsCollector:
    """
    Collects container metrics from Docker Stats API.
    Runs as a Celery beat task every 5 seconds.
    """
    
    def __init__(self):
        self.docker = None
        self.redis_client = None
        self._running = False
    
    async def _get_docker(self):
        if not self.docker:
            self.docker = await get_docker_client()
        return self.docker
    
    async def _get_redis(self):
        if not self.redis_client:
            self.redis_client = redis.from_url(settings.redis_url)
        return self.redis_client
    
    async def collect_all(self):
        """Collect metrics for all running containers"""
        docker = await self._get_docker()
        
        # Get all running containers with nukelab labels
        containers = await docker.list_containers(
            filters={"status": ["running"], "label": ["nukelab.server.id"]}
        )
        
        for container_info in containers:
            try:
                await self._collect_container_metrics(docker, container_info)
            except Exception as e:
                print(f"Error collecting metrics for {container_info['Id']}: {e}")
    
    async def _collect_container_metrics(self, docker, container_info):
        """Collect metrics for a single container"""
        container_id = container_info['Id']
        labels = container_info.get('Labels', {})
        server_id = labels.get('nukelab.server.id')
        
        if not server_id:
            return
        
        # Get container stats
        container = await docker.client.containers.get(container_id)
        stats = await container.stats(stream=False)
        
        # Parse stats
        metrics = self._parse_docker_stats(stats, server_id, container_id)
        
        # Persist to database
        await self._persist_metrics(metrics)
        
        # Broadcast via Redis
        await self._broadcast_metrics(metrics)
    
    def _parse_docker_stats(self, stats: dict, server_id: str, container_id: str) -> dict:
        """Parse raw Docker stats into normalized metrics"""
        
        # CPU calculation
        cpu_delta = (
            stats['cpu_stats']['cpu_usage']['total_usage'] - 
            stats['precpu_stats']['cpu_usage']['total_usage']
        )
        system_delta = (
            stats['cpu_stats']['system_cpu_usage'] - 
            stats['precpu_stats']['system_cpu_usage']
        )
        
        cpu_percent = 0.0
        if system_delta > 0 and cpu_delta > 0:
            cpu_count = len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', []))
            if cpu_count == 0:
                cpu_count = 1
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
        
        # Memory
        memory_stats = stats.get('memory_stats', {})
        memory_usage = memory_stats.get('usage', 0)
        memory_limit = memory_stats.get('limit', 1)
        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0
        
        # Disk I/O
        blkio_stats = stats.get('blkio_stats', {})
        io_service_bytes = blkio_stats.get('io_service_bytes_recursive', [])
        disk_read = sum(item['value'] for item in io_service_bytes if item['op'] == 'Read')
        disk_write = sum(item['value'] for item in io_service_bytes if item['op'] == 'Write')
        
        # Network
        networks = stats.get('networks', {})
        network_rx = sum(n.get('rx_bytes', 0) for n in networks.values())
        network_tx = sum(n.get('tx_bytes', 0) for n in networks.values())
        
        return {
            'server_id': server_id,
            'container_id': container_id,
            'cpu_percent': round(cpu_percent, 2),
            'cpu_usage_ns': stats['cpu_stats']['cpu_usage']['total_usage'],
            'cpu_system_ns': stats['cpu_stats']['system_cpu_usage'],
            'cpu_cores': cpu_count,
            'memory_used': memory_usage,
            'memory_total': memory_limit,
            'memory_percent': round(memory_percent, 2),
            'memory_cache': memory_stats.get('stats', {}).get('cache', 0),
            'memory_swap_used': memory_stats.get('stats', {}).get('swap', 0),
            'disk_read_bytes': disk_read,
            'disk_write_bytes': disk_write,
            'network_rx_bytes': network_rx,
            'network_tx_bytes': network_tx,
            'pids': stats['pids_stats'].get('current', 0),
            'collected_at': datetime.utcnow(),
        }
    
    async def _persist_metrics(self, metrics: dict):
        """Save metrics to database"""
        async for db in get_db():
            metric = ServerMetric(**metrics)
            db.add(metric)
            await db.commit()
            break  # Only need one session
    
    async def _broadcast_metrics(self, metrics: dict):
        """Broadcast metrics via Redis pub/sub"""
        redis_client = await self._get_redis()
        await redis_client.publish(
            f"metrics:server:{metrics['server_id']}",
            json.dumps(metrics, default=str)
        )
        await redis_client.publish(
            "metrics:all",
            json.dumps(metrics, default=str)
        )


collector = MetricsCollector()
```

#### `backend/app/services/system_metrics_collector.py` — Host-Level Metrics

```python
import psutil
import asyncio
from datetime import datetime
from typing import Dict
import aiodocker
from app.docker.client import get_docker_client

class SystemMetricsCollector:
    """Collect host-level system metrics"""
    
    async def collect(self) -> Dict:
        """Collect current system metrics"""
        
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load_avg = psutil.getloadavg()
        
        # Memory
        memory = psutil.virtual_memory()
        
        # Disk
        disk = psutil.disk_usage('/')
        disk_io = psutil.disk_io_counters()
        
        # Network
        net_io = psutil.net_io_counters()
        
        # Docker stats
        docker = await get_docker_client()
        containers = await docker.list_containers()
        running = sum(1 for c in c['State'] == 'running' for c in containers)
        images = await docker.client.images.list()
        
        return {
            'host': 'localhost',
            'cpu_percent': cpu_percent,
            'cpu_count': cpu_count,
            'cpu_load_1m': load_avg[0],
            'cpu_load_5m': load_avg[1],
            'cpu_load_15m': load_avg[2],
            'memory_used': memory.used,
            'memory_total': memory.total,
            'memory_percent': memory.percent,
            'memory_available': memory.available,
            'disk_used': disk.used,
            'disk_total': disk.total,
            'disk_percent': (disk.used / disk.total) * 100,
            'disk_read_bytes': disk_io.read_bytes if disk_io else 0,
            'disk_write_bytes': disk_io.write_bytes if disk_io else 0,
            'network_rx_bytes': net_io.bytes_recv if net_io else 0,
            'network_tx_bytes': net_io.bytes_sent if net_io else 0,
            'docker_containers_running': running,
            'docker_containers_total': len(containers),
            'docker_images_total': len(images),
            'collected_at': datetime.utcnow(),
        }
```

#### `backend/app/services/alert_service.py` — Alert Rule Evaluation

```python
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.server_metric import ServerMetric
from app.models.user import User

class AlertService:
    """Evaluate alert rules and manage alert lifecycle"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def evaluate_all_rules(self):
        """Evaluate all active alert rules against latest metrics"""
        # Get all active rules
        result = await self.db.execute(
            select(AlertRule).where(AlertRule.is_active == True)
        )
        rules = result.scalars().all()
        
        for rule in rules:
            try:
                await self._evaluate_rule(rule)
            except Exception as e:
                print(f"Error evaluating rule {rule.id}: {e}")
    
    async def _evaluate_rule(self, rule: AlertRule):
        """Evaluate a single rule"""
        # Get latest metrics based on scope
        metrics = await self._get_metrics_for_rule(rule)
        
        for metric in metrics:
            value = self._extract_metric_value(metric, rule.metric_type)
            if value is None:
                continue
            
            # Check if threshold breached
            if rule.evaluate(value):
                await self._handle_breach(rule, metric, value)
            else:
                await self._check_resolution(rule, metric, value)
    
    async def _handle_breach(self, rule: AlertRule, metric: ServerMetric, value: float):
        """Handle threshold breach"""
        # Check if already alerted (cooldown)
        recent_alert = await self.db.execute(
            select(AlertHistory).where(
                and_(
                    AlertHistory.rule_id == rule.id,
                    AlertHistory.server_id == metric.server_id,
                    AlertHistory.status.in_(["fired", "acknowledged"]),
                    AlertHistory.fired_at >= datetime.utcnow() - timedelta(seconds=rule.cooldown_seconds)
                )
            )
        )
        
        if recent_alert.scalar_one_or_none():
            return  # Still in cooldown
        
        # Create alert
        alert = AlertHistory(
            rule_id=rule.id,
            server_id=metric.server_id,
            metric_value=value,
            threshold=rule.threshold,
        )
        
        self.db.add(alert)
        await self.db.commit()
        
        # Send notifications
        await self._send_notifications(rule, alert)
    
    async def _send_notifications(self, rule: AlertRule, alert: AlertHistory):
        """Send notifications for an alert"""
        # Get server owner
        result = await self.db.execute(
            select(User).where(User.id == alert.server_id)
        )
        user = result.scalar_one_or_none()
        
        if rule.notify_admin:
            # TODO: Send admin notification (in-app, email, webhook)
            alert.admin_notified = True
        
        if rule.notify_user and user:
            # TODO: Send user notification
            alert.user_notified = True
        
        if rule.email_enabled:
            # TODO: Send email
            alert.email_sent = True
        
        if rule.webhook_url:
            # TODO: Send webhook
            alert.webhook_sent = True
        
        await self.db.commit()
    
    def _extract_metric_value(self, metric: ServerMetric, metric_type: str) -> Optional[float]:
        """Extract the relevant value from a metric based on type"""
        mapping = {
            'cpu': metric.cpu_percent,
            'memory': metric.memory_percent,
            'disk': metric.disk_read_bytes,  # Or write, or combined
            'gpu': metric.gpu_percent,
            'pids': metric.pids,
        }
        return mapping.get(metric_type)
```

#### `backend/app/services/health_check_service.py` — Container Health Checks

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.docker.client import get_docker_client
from app.models.health_check import HealthCheck
from app.models.server import Server

class HealthCheckService:
    """Perform and track container health checks"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def check_all_containers(self):
        """Check health of all running containers"""
        docker = await get_docker_client()
        
        # Get all running servers
        result = await self.db.execute(
            select(Server).where(Server.status == "running")
        )
        servers = result.scalars().all()
        
        for server in servers:
            if not server.container_id:
                continue
            
            try:
                await self._check_container(server)
            except Exception as e:
                print(f"Health check failed for {server.id}: {e}")
    
    async def _check_container(self, server: Server):
        """Check health of a single container"""
        docker = await get_docker_client()
        
        try:
            container = await docker.client.containers.get(server.container_id)
            info = await container.show()
            state = info.get('State', {})
            
            health = state.get('Health', {})
            health_status = health.get('Status', 'unknown')
            
            # If no health check configured, use running state
            if health_status == 'unknown':
                if state.get('Running'):
                    health_status = 'healthy'
                else:
                    health_status = 'unhealthy'
            
            # Get last check output
            log = health.get('Log', [])
            last_check = log[-1] if log else {}
            
            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id,
                status=health_status,
                exit_code=last_check.get('ExitCode'),
                output=last_check.get('Output', '')[:1000],  # Truncate
            )
            
            # Track consecutive failures
            if health_status == 'unhealthy':
                last_check_result = await self.db.execute(
                    select(HealthCheck).where(
                        HealthCheck.server_id == server.id
                    ).order_by(HealthCheck.checked_at.desc()).limit(1)
                )
                last = last_check_result.scalar_one_or_none()
                if last and last.status == 'unhealthy':
                    health_check.consecutive_failures = last.consecutive_failures + 1
                else:
                    health_check.consecutive_failures = 1
            else:
                health_check.last_success_at = datetime.utcnow()
            
            self.db.add(health_check)
            await self.db.commit()
            
            # Auto-restart if too many failures
            if health_check.consecutive_failures >= 3:
                await self._auto_restart(server)
                
        except Exception as e:
            # Container not found or other error
            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id or '',
                status='unknown',
                output=str(e)[:1000],
            )
            self.db.add(health_check)
            await self.db.commit()
    
    async def _auto_restart(self, server: Server):
        """Auto-restart a failed container"""
        # TODO: Implement auto-restart with rate limiting
        pass
```

### 3. WebSocket Server

#### `backend/app/websocket/metrics_socket.py`

```python
import json
from typing import Set, Dict
import socketio
from app.config import settings
import redis.asyncio as redis

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*" if settings.app_debug else [settings.app_url],
    logger=True,
)

# Wrap with ASGI app
socket_app = socketio.ASGIApp(sio)

# Track active subscriptions
subscriptions: Dict[str, Set[str]] = {}  # room -> set of sid


class MetricsWebSocketManager:
    """Manages WebSocket connections and metric broadcasting"""
    
    def __init__(self):
        self.redis_client = None
        self._pubsub_task = None
    
    async def get_redis(self):
        if not self.redis_client:
            self.redis_client = redis.from_url(settings.redis_url)
        return self.redis_client
    
    async def start_redis_listener(self):
        """Start listening to Redis pub/sub for metrics"""
        redis_client = await self.get_redis()
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("metrics:all")
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await self._broadcast_metric(data)
    
    async def _broadcast_metric(self, metric: dict):
        """Broadcast metric to subscribed clients"""
        server_id = metric.get('server_id')
        
        # Broadcast to server-specific room
        if server_id:
            await sio.emit(
                'metrics:server',
                metric,
                room=f"server:{server_id}"
            )
        
        # Broadcast to global room
        await sio.emit(
            'metrics:all',
            metric,
            room="global"
        )


manager = MetricsWebSocketManager()


# Socket.IO event handlers
@sio.event
async def connect(sid, environ):
    """Handle client connection"""
    print(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    """Handle client disconnect"""
    print(f"Client disconnected: {sid}")
    # Remove from all rooms
    for room, sids in subscriptions.items():
        sids.discard(sid)


@sio.on('subscribe')
async def handle_subscribe(sid, data):
    """Handle subscription request"""
    scope = data.get('scope', 'global')  # global, server, user
    target_id = data.get('target_id')
    
    if scope == 'server' and target_id:
        room = f"server:{target_id}"
    elif scope == 'user' and target_id:
        room = f"user:{target_id}"
    else:
        room = "global"
    
    sio.enter_room(sid, room)
    
    if room not in subscriptions:
        subscriptions[room] = set()
    subscriptions[room].add(sid)
    
    await sio.emit('subscribed', {'scope': scope, 'target_id': target_id}, room=sid)


@sio.on('unsubscribe')
async def handle_unsubscribe(sid, data):
    """Handle unsubscription request"""
    scope = data.get('scope', 'global')
    target_id = data.get('target_id')
    
    if scope == 'server' and target_id:
        room = f"server:{target_id}"
    elif scope == 'user' and target_id:
        room = f"user:{target_id}"
    else:
        room = "global"
    
    sio.leave_room(sid, room)
    
    if room in subscriptions:
        subscriptions[room].discard(sid)
    
    await sio.emit('unsubscribed', {'scope': scope, 'target_id': target_id}, room=sid)
```

### 4. API Endpoints

#### `backend/app/api/metrics.py` — REST API for Metrics

```python
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.system_metric import SystemMetric
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.health_check import HealthCheck

router = APIRouter()


# ========== Server Metrics ==========

@router.get("/servers/{server_id}")
async def get_server_metrics(
    server_id: str,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    interval: str = Query("1m"),  # 1m, 5m, 1h, 1d
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get metrics history for a server"""
    # TODO: Check permission (own server or admin)
    
    if not from_date:
        from_date = datetime.utcnow() - timedelta(hours=1)
    if not to_date:
        to_date = datetime.utcnow()
    
    query = select(ServerMetric).where(
        and_(
            ServerMetric.server_id == server_id,
            ServerMetric.collected_at >= from_date,
            ServerMetric.collected_at <= to_date
        )
    ).order_by(desc(ServerMetric.collected_at))
    
    result = await db.execute(query)
    metrics = result.scalars().all()
    
    return {
        "metrics": [m.to_dict() for m in metrics],
        "count": len(metrics),
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    }


@router.get("/servers/{server_id}/latest")
async def get_server_latest_metrics(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get latest metrics for a server"""
    result = await db.execute(
        select(ServerMetric).where(
            ServerMetric.server_id == server_id
        ).order_by(desc(ServerMetric.collected_at)).limit(1)
    )
    metric = result.scalar_one_or_none()
    
    if not metric:
        raise HTTPException(status_code=404, detail="No metrics found")
    
    return metric.to_dict()


@router.get("/global")
async def get_global_metrics(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get global resource overview (admin only)"""
    
    # Total running servers
    total_servers_result = await db.execute(
        select(func.count()).where(Server.status == "running")
    )
    total_running = total_servers_result.scalar()
    
    # Aggregate resource usage
    latest_metrics = await db.execute(
        select(
            func.avg(ServerMetric.cpu_percent).label('avg_cpu'),
            func.avg(ServerMetric.memory_percent).label('avg_memory'),
            func.sum(ServerMetric.memory_used).label('total_memory_used'),
            func.sum(ServerMetric.network_rx_bytes).label('total_rx'),
            func.sum(ServerMetric.network_tx_bytes).label('total_tx'),
        ).where(
            ServerMetric.collected_at >= datetime.utcnow() - timedelta(minutes=5)
        )
    )
    
    agg = latest_metrics.one()
    
    return {
        "servers": {
            "total_running": total_running,
        },
        "resources": {
            "avg_cpu_percent": round(agg.avg_cpu or 0, 2),
            "avg_memory_percent": round(agg.avg_memory or 0, 2),
            "total_memory_used": agg.total_memory_used or 0,
            "total_network_rx": agg.total_rx or 0,
            "total_network_tx": agg.total_tx or 0,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/users/{user_id}")
async def get_user_metrics(
    user_id: str,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated metrics for a user"""
    # TODO: Permission check
    
    if not from_date:
        from_date = datetime.utcnow() - timedelta(hours=24)
    if not to_date:
        to_date = datetime.utcnow()
    
    # Get user's servers
    servers_result = await db.execute(
        select(Server).where(Server.user_id == user_id)
    )
    servers = servers_result.scalars().all()
    server_ids = [str(s.id) for s in servers]
    
    if not server_ids:
        return {"servers": [], "aggregated": None}
    
    # Get metrics for all user's servers
    metrics_result = await db.execute(
        select(ServerMetric).where(
            and_(
                ServerMetric.server_id.in_(server_ids),
                ServerMetric.collected_at >= from_date,
                ServerMetric.collected_at <= to_date
            )
        ).order_by(desc(ServerMetric.collected_at))
    )
    metrics = metrics_result.scalars().all()
    
    # Aggregate
    if metrics:
        avg_cpu = sum(m.cpu_percent or 0 for m in metrics) / len(metrics)
        avg_memory = sum(m.memory_percent or 0 for m in metrics) / len(metrics)
        total_memory = max(m.memory_total or 0 for m in metrics)
    else:
        avg_cpu = avg_memory = total_memory = 0
    
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status,
            }
            for s in servers
        ],
        "aggregated": {
            "avg_cpu_percent": round(avg_cpu, 2),
            "avg_memory_percent": round(avg_memory, 2),
            "total_memory_allocated": total_memory,
            "metric_count": len(metrics),
        },
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    }


# ========== System Metrics ==========

@router.get("/system")
async def get_system_metrics(
    hours: int = Query(1, ge=1, le=168),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get host-level system metrics history"""
    from_date = datetime.utcnow() - timedelta(hours=hours)
    
    result = await db.execute(
        select(SystemMetric).where(
            SystemMetric.collected_at >= from_date
        ).order_by(desc(SystemMetric.collected_at))
    )
    metrics = result.scalars().all()
    
    return {
        "metrics": [
            {
                "cpu_percent": m.cpu_percent,
                "memory_percent": m.memory_percent,
                "disk_percent": m.disk_percent,
                "docker_containers_running": m.docker_containers_running,
                "collected_at": m.collected_at.isoformat(),
            }
            for m in metrics
        ],
        "count": len(metrics),
    }


# ========== Alert Rules ==========

class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    metric_type: str  # cpu, memory, disk, gpu, pids
    operator: str  # >, <, >=, <=, ==, !=
    threshold: float
    scope: str = "global"  # global, user, server, plan
    target_id: Optional[str] = None
    duration_seconds: int = 60
    cooldown_seconds: int = 300
    notify_admin: bool = True
    notify_user: bool = True


@router.get("/alerts/rules")
async def list_alert_rules(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """List all alert rules"""
    result = await db.execute(select(AlertRule))
    rules = result.scalars().all()
    return {"rules": [r.to_dict() for r in rules]}


@router.post("/alerts/rules")
async def create_alert_rule(
    rule: AlertRuleCreate,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Create a new alert rule"""
    new_rule = AlertRule(
        name=rule.name,
        description=rule.description,
        metric_type=rule.metric_type,
        operator=rule.operator,
        threshold=rule.threshold,
        scope=rule.scope,
        target_id=rule.target_id,
        duration_seconds=rule.duration_seconds,
        cooldown_seconds=rule.cooldown_seconds,
        notify_admin=rule.notify_admin,
        notify_user=rule.notify_user,
        created_by=current_user.id,
    )
    
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    
    return {"success": True, "rule": new_rule.to_dict()}


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Delete (deactivate) an alert rule"""
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    rule.is_active = False
    await db.commit()
    
    return {"success": True, "message": "Rule deactivated"}


# ========== Alert History ==========

@router.get("/alerts/history")
async def get_alert_history(
    status: Optional[str] = Query(None),
    server_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get alert history with filtering"""
    query = select(AlertHistory)
    
    if status:
        query = query.where(AlertHistory.status == status)
    if server_id:
        query = query.where(AlertHistory.server_id == server_id)
    if user_id:
        query = query.where(AlertHistory.user_id == user_id)
    
    # Count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()
    
    # Paginate
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit).order_by(desc(AlertHistory.fired_at))
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    
    return {
        "alerts": [a.to_dict() for a in alerts],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    notes: Optional[str] = None,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Acknowledge an alert"""
    result = await db.execute(
        select(AlertHistory).where(AlertHistory.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.status = "acknowledged"
    alert.acknowledged_by = current_user.id
    alert.acknowledged_at = datetime.utcnow()
    alert.notes = notes
    
    await db.commit()
    
    return {"success": True, "alert": alert.to_dict()}


# ========== Health Checks ==========

@router.get("/health/servers/{server_id}")
async def get_server_health(
    server_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get health check history for a server"""
    result = await db.execute(
        select(HealthCheck).where(
            HealthCheck.server_id == server_id
        ).order_by(desc(HealthCheck.checked_at)).limit(limit)
    )
    checks = result.scalars().all()
    
    return {
        "checks": [
            {
                "status": c.status,
                "exit_code": c.exit_code,
                "output": c.output,
                "consecutive_failures": c.consecutive_failures,
                "checked_at": c.checked_at.isoformat(),
            }
            for c in checks
        ]
    }


@router.get("/health/summary")
async def get_health_summary(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get health check summary for all servers"""
    # Get latest health check per server
    from sqlalchemy import distinct
    
    result = await db.execute(
        select(HealthCheck).distinct(HealthCheck.server_id).order_by(
            HealthCheck.server_id,
            desc(HealthCheck.checked_at)
        )
    )
    latest_checks = result.scalars().all()
    
    healthy = sum(1 for c in latest_checks if c.status == 'healthy')
    unhealthy = sum(1 for c in latest_checks if c.status == 'unhealthy')
    unknown = sum(1 for c in latest_checks if c.status == 'unknown')
    
    return {
        "summary": {
            "total": len(latest_checks),
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unknown": unknown,
        },
        "servers": [
            {
                "server_id": str(c.server_id),
                "status": c.status,
                "consecutive_failures": c.consecutive_failures,
                "last_check": c.checked_at.isoformat(),
            }
            for c in latest_checks
        ]
    }
```

### 5. Celery Tasks

#### `backend/app/tasks/metrics_tasks.py`

```python
from app.worker import celery_app
from app.services.metrics_collector import collector
from app.services.system_metrics_collector import SystemMetricsCollector
from app.services.alert_service import AlertService
from app.services.health_check_service import HealthCheckService
from app.db.session import get_db
from app.models.system_metric import SystemMetric

@celery_app.task(bind=True)
def collect_container_metrics(self):
    """Collect metrics for all running containers"""
    import asyncio
    asyncio.run(collector.collect_all())
    return f"Collected metrics for all containers"


@celery_app.task(bind=True)
def collect_system_metrics(self):
    """Collect host-level system metrics"""
    import asyncio
    
    async def _collect():
        collector = SystemMetricsCollector()
        metrics = await collector.collect()
        
        async for db in get_db():
            metric = SystemMetric(**metrics)
            db.add(metric)
            await db.commit()
            break
    
    asyncio.run(_collect())
    return "System metrics collected"


@celery_app.task(bind=True)
def evaluate_alert_rules(self):
    """Evaluate all alert rules"""
    import asyncio
    
    async def _evaluate():
        async for db in get_db():
            service = AlertService(db)
            await service.evaluate_all_rules()
            break
    
    asyncio.run(_evaluate())
    return "Alert rules evaluated"


@celery_app.task(bind=True)
def check_container_health(self):
    """Check health of all containers"""
    import asyncio
    
    async def _check():
        async for db in get_db():
            service = HealthCheckService(db)
            await service.check_all_containers()
            break
    
    asyncio.run(_check())
    return "Container health checks completed"


@celery_app.task(bind=True)
def cleanup_old_metrics(self):
    """Delete metrics older than retention period"""
    from datetime import datetime, timedelta
    from sqlalchemy import text
    import asyncio
    
    async def _cleanup():
        retention_days = 30
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        
        async for db in get_db():
            # Delete old metrics from partitioned tables
            result = await db.execute(
                text("""
                    DELETE FROM server_metrics 
                    WHERE collected_at < :cutoff
                """),
                {"cutoff": cutoff}
            )
            await db.commit()
            
            return f"Deleted {result.rowcount} old metrics"
    
    return asyncio.run(_cleanup())
```

#### `backend/app/tasks.py` (Update existing)

Add to existing tasks.py:

```python
from app.tasks.metrics_tasks import (
    collect_container_metrics,
    collect_system_metrics,
    evaluate_alert_rules,
    check_container_health,
    cleanup_old_metrics,
)
```

#### Celery Beat Schedule (Update `backend/app/worker.py`)

```python
from celery import Celery
from app.config import settings

celery_app = Celery(
    "nukelab",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.beat_schedule = {
    # Metrics collection every 5 seconds
    'collect-container-metrics': {
        'task': 'app.tasks.metrics_tasks.collect_container_metrics',
        'schedule': 5.0,
    },
    # System metrics every 30 seconds
    'collect-system-metrics': {
        'task': 'app.tasks.metrics_tasks.collect_system_metrics',
        'schedule': 30.0,
    },
    # Alert evaluation every minute
    'evaluate-alerts': {
        'task': 'app.tasks.metrics_tasks.evaluate_alert_rules',
        'schedule': 60.0,
    },
    # Health checks every 2 minutes
    'check-health': {
        'task': 'app.tasks.metrics_tasks.check_container_health',
        'schedule': 120.0,
    },
    # Cleanup old metrics daily
    'cleanup-metrics': {
        'task': 'app.tasks.metrics_tasks.cleanup_old_metrics',
        'schedule': 86400.0,  # 24 hours
    },
    # Existing tasks...
    'cleanup-inactive-servers': {
        'task': 'app.tasks.cleanup_inactive_servers',
        'schedule': 3600.0,
    },
}
```

### 6. Main App Integration

Update `backend/app/main.py` to include metrics API and WebSocket:

```python
from fastapi import FastAPI
from app.api import metrics
from app.websocket.metrics_socket import socket_app

# Add metrics router
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])

# Mount WebSocket app
app.mount("/ws", socket_app)
```

---

## Frontend Implementation

### 1. WebSocket Client Hook

#### `frontend/src/hooks/useMetricsSocket.ts`

```typescript
import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuthStore } from '@/stores/authStore';

interface MetricData {
  server_id: string;
  container_id: string;
  cpu: {
    percent: number;
    cores: number;
  };
  memory: {
    used: number;
    total: number;
    percent: number;
  };
  network: {
    rx_bytes: number;
    tx_bytes: number;
  };
  collected_at: string;
}

interface UseMetricsSocketOptions {
  scope: 'global' | 'server' | 'user';
  targetId?: string;
  onMetric?: (metric: MetricData) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function useMetricsSocket(options: UseMetricsSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [latestMetric, setLatestMetric] = useState<MetricData | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const { token } = useAuthStore();

  const connect = useCallback(() => {
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
    const socket = new WebSocket(wsUrl);
    
    socket.onopen = () => {
      setIsConnected(true);
      options.onConnect?.();
      
      // Subscribe to metrics
      socket.send(JSON.stringify({
        type: 'subscribe',
        scope: options.scope,
        target_id: options.targetId,
      }));
    };
    
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'metrics:server' || data.type === 'metrics:all') {
        setLatestMetric(data);
        options.onMetric?.(data);
      }
    };
    
    socket.onclose = () => {
      setIsConnected(false);
      options.onDisconnect?.();
      
      // Auto-reconnect after 3 seconds
      setTimeout(connect, 3000);
    };
    
    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    socketRef.current = socket;
  }, [options.scope, options.targetId]);

  const disconnect = useCallback(() => {
    socketRef.current?.close();
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return {
    isConnected,
    latestMetric,
    connect,
    disconnect,
  };
}
```

### 2. Dashboard Components

#### `frontend/src/components/monitoring/ServerMetricsChart.tsx`

```typescript
'use client';

import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useMetricsSocket } from '@/hooks/useMetricsSocket';

interface MetricPoint {
  timestamp: string;
  cpu: number;
  memory: number;
  network_rx: number;
  network_tx: number;
}

interface ServerMetricsChartProps {
  serverId: string;
  maxPoints?: number;
}

export function ServerMetricsChart({ serverId, maxPoints = 60 }: ServerMetricsChartProps) {
  const [data, setData] = useState<MetricPoint[]>([]);
  
  const { isConnected } = useMetricsSocket({
    scope: 'server',
    targetId: serverId,
    onMetric: (metric) => {
      setData(prev => {
        const newPoint: MetricPoint = {
          timestamp: new Date().toLocaleTimeString(),
          cpu: metric.cpu.percent,
          memory: metric.memory.percent,
          network_rx: metric.network.rx_bytes,
          network_tx: metric.network.tx_bytes,
        };
        
        const newData = [...prev, newPoint];
        if (newData.length > maxPoints) {
          return newData.slice(-maxPoints);
        }
        return newData;
      });
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Real-Time Metrics</h3>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm text-muted-foreground">
            {isConnected ? 'Live' : 'Reconnecting...'}
          </span>
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        {/* CPU Chart */}
        <div className="bg-card rounded-lg border p-4">
          <h4 className="text-sm font-medium mb-2">CPU Usage (%)</h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tick={{fontSize: 12}} />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Line 
                type="monotone" 
                dataKey="cpu" 
                stroke="#2563eb" 
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        
        {/* Memory Chart */}
        <div className="bg-card rounded-lg border p-4">
          <h4 className="text-sm font-medium mb-2">Memory Usage (%)</h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tick={{fontSize: 12}} />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Line 
                type="monotone" 
                dataKey="memory" 
                stroke="#16a34a" 
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
```

#### `frontend/src/components/monitoring/GlobalMetricsOverview.tsx`

```typescript
'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { useMetricsSocket } from '@/hooks/useMetricsSocket';
import { api } from '@/lib/api';

interface GlobalMetrics {
  servers: {
    total_running: number;
  };
  resources: {
    avg_cpu_percent: number;
    avg_memory_percent: number;
    total_memory_used: number;
    total_network_rx: number;
    total_network_tx: number;
  };
}

export function GlobalMetricsOverview() {
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  
  useMetricsSocket({
    scope: 'global',
    onMetric: () => {
      // Refresh global metrics on new data
      fetchGlobalMetrics();
    },
  });

  const fetchGlobalMetrics = async () => {
    try {
      const response = await api.get('/metrics/global');
      setMetrics(response.data);
    } catch (error) {
      console.error('Failed to fetch global metrics:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGlobalMetrics();
    const interval = setInterval(fetchGlobalMetrics, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading metrics...</div>;
  if (!metrics) return <div>No metrics available</div>;

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Running Servers</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{metrics.servers.total_running}</div>
        </CardContent>
      </Card>
      
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Avg CPU Usage</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{metrics.resources.avg_cpu_percent.toFixed(1)}%</div>
          <Progress value={metrics.resources.avg_cpu_percent} className="mt-2" />
        </CardContent>
      </Card>
      
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Avg Memory Usage</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{metrics.resources.avg_memory_percent.toFixed(1)}%</div>
          <Progress value={metrics.resources.avg_memory_percent} className="mt-2" />
        </CardContent>
      </Card>
      
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Network I/O</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <div className="text-sm">
              ↓ {formatBytes(metrics.resources.total_network_rx)}
            </div>
            <div className="text-sm">
              ↑ {formatBytes(metrics.resources.total_network_tx)}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

### 3. Dashboard Pages

#### `frontend/src/app/dashboard/monitoring/page.tsx` — Admin Monitoring Dashboard

```typescript
'use client';

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { GlobalMetricsOverview } from '@/components/monitoring/GlobalMetricsOverview';
import { ServerMetricsChart } from '@/components/monitoring/ServerMetricsChart';
import { AlertHistoryTable } from '@/components/monitoring/AlertHistoryTable';
import { HealthStatusGrid } from '@/components/monitoring/HealthStatusGrid';
import { SystemMetricsChart } from '@/components/monitoring/SystemMetricsChart';

export default function MonitoringPage() {
  const [selectedServer, setSelectedServer] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Monitoring Dashboard</h1>
        <p className="text-muted-foreground">
          Real-time resource monitoring and system health
        </p>
      </div>

      <GlobalMetricsOverview />

      <Tabs defaultValue="servers" className="space-y-4">
        <TabsList>
          <TabsTrigger value="servers">Server Metrics</TabsTrigger>
          <TabsTrigger value="system">System Metrics</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
          <TabsTrigger value="health">Health Checks</TabsTrigger>
        </TabsList>

        <TabsContent value="servers" className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Server selector */}
            <div className="col-span-2">
              <ServerSelector onSelect={setSelectedServer} />
            </div>
            
            {selectedServer && (
              <>
                <div className="col-span-2">
                  <ServerMetricsChart serverId={selectedServer} />
                </div>
                
                <ServerResourceUsage serverId={selectedServer} />
                <ServerNetworkUsage serverId={selectedServer} />
              </>
            )}
          </div>
        </TabsContent>

        <TabsContent value="system">
          <SystemMetricsChart />
        </TabsContent>

        <TabsContent value="alerts">
          <AlertHistoryTable />
        </TabsContent>

        <TabsContent value="health">
          <HealthStatusGrid />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

#### `frontend/src/app/dashboard/user/usage/page.tsx` — User Resource Usage

```typescript
'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { useAuthStore } from '@/stores/authStore';
import { api } from '@/lib/api';
import { ServerMetricsChart } from '@/components/monitoring/ServerMetricsChart';

interface UserUsageData {
  servers: Array<{
    id: string;
    name: string;
    status: string;
  }>;
  aggregated: {
    avg_cpu_percent: number;
    avg_memory_percent: number;
    total_memory_allocated: number;
    metric_count: number;
  };
}

export default function UserUsagePage() {
  const { user } = useAuthStore();
  const [usage, setUsage] = useState<UserUsageData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (user?.id) {
      fetchUsage(user.id);
    }
  }, [user]);

  const fetchUsage = async (userId: string) => {
    try {
      const response = await api.get(`/metrics/users/${userId}`);
      setUsage(response.data);
    } catch (error) {
      console.error('Failed to fetch usage:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading usage data...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">My Resource Usage</h1>
        <p className="text-muted-foreground">
          Monitor your server resource consumption
        </p>
      </div>

      {usage?.aggregated && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Avg CPU Usage</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {usage.aggregated.avg_cpu_percent.toFixed(1)}%
              </div>
              <Progress value={usage.aggregated.avg_cpu_percent} />
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Avg Memory Usage</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {usage.aggregated.avg_memory_percent.toFixed(1)}%
              </div>
              <Progress value={usage.aggregated.avg_memory_percent} />
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Active Servers</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {usage.servers.length}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Per-Server Metrics</h2>
        {usage?.servers.map((server) => (
          <div key={server.id} className="border rounded-lg p-4">
            <h3 className="font-medium mb-4">{server.name}</h3>
            <ServerMetricsChart serverId={server.id} maxPoints={30} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

### 4. Update Sidebar Navigation

Update `frontend/src/app/dashboard/layout.tsx` to add monitoring links:

```typescript
// Add to sidebar navigation
const adminNavItems = [
  // ... existing items
  {
    title: "Monitoring",
    href: "/dashboard/monitoring",
    icon: Activity,
  },
];

const userNavItems = [
  // ... existing items
  {
    title: "My Usage",
    href: "/dashboard/user/usage",
    icon: BarChart3,
  },
];
```

---

## API Design Summary

### REST Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/metrics/servers/{id}` | Server metrics history | User (own) / Admin |
| GET | `/api/metrics/servers/{id}/latest` | Latest server metrics | User (own) / Admin |
| GET | `/api/metrics/global` | Global resource overview | Admin |
| GET | `/api/metrics/users/{id}` | User's aggregated metrics | User (own) / Admin |
| GET | `/api/metrics/system` | Host-level system metrics | Admin |
| GET | `/api/metrics/alerts/rules` | List alert rules | Admin |
| POST | `/api/metrics/alerts/rules` | Create alert rule | Admin |
| DELETE | `/api/metrics/alerts/rules/{id}` | Deactivate rule | Admin |
| GET | `/api/metrics/alerts/history` | Alert history | Admin |
| POST | `/api/metrics/alerts/{id}/acknowledge` | Acknowledge alert | Admin |
| GET | `/api/metrics/health/servers/{id}` | Server health checks | User (own) / Admin |
| GET | `/api/metrics/health/summary` | Health summary | Admin |

### WebSocket Events

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `connect` | C→S | — | Client connects |
| `subscribe` | C→S | `{scope, target_id}` | Subscribe to metrics |
| `unsubscribe` | C→S | `{scope, target_id}` | Unsubscribe |
| `metrics:server` | S→C | Metric data | Server-specific metrics |
| `metrics:all` | S→C | Metric data | All metrics broadcast |
| `subscribed` | S→C | `{scope, target_id}` | Subscription confirmed |

---

## Testing Strategy

### Backend Tests

```
backend/tests/
├── unit/
│   ├── test_metrics_collector.py      # Docker stats parsing
│   ├── test_alert_service.py          # Rule evaluation
│   ├── test_health_check_service.py   # Health check logic
│   └── test_websocket_manager.py      # WebSocket subscriptions
├── integration/
│   ├── test_metrics_api.py            # REST endpoints
│   ├── test_websocket.py              # WebSocket connections
│   └── test_alert_rules.py            # Alert lifecycle
└── e2e/
    └── test_monitoring_flow.py        # Full flow
```

### Frontend Tests

```
frontend/src/__tests__/
├── components/
│   ├── monitoring/
│   │   ├── ServerMetricsChart.test.tsx
│   │   ├── GlobalMetricsOverview.test.tsx
│   │   └── AlertHistoryTable.test.tsx
└── hooks/
    └── useMetricsSocket.test.ts
```

### Key Test Scenarios

1. **Metrics Collection**
   - Docker Stats API returns valid data → parsed correctly
   - Container stops mid-collection → handled gracefully
   - High-frequency collection → no database lockups

2. **WebSocket Streaming**
   - Client subscribes to server → receives metrics
   - Client disconnects → cleanup, no memory leaks
   - Multiple clients → broadcast works correctly

3. **Alert Rules**
   - CPU > 90% for 60s → alert fired
   - CPU > 90% for 30s → no alert (duration not met)
   - Alert in cooldown → no duplicate
   - Metric returns to normal → alert resolved

4. **Health Checks**
   - Container healthy → status recorded
   - 3 consecutive failures → auto-restart triggered
   - Container removed → unknown status

---

## Week-by-Week Breakdown

### Week 10: Metrics Collection & Storage

**Day 1-2: Database Schema**
- [ ] Create migration for `server_metrics`, `system_metrics`, `alert_rules`, `alert_history`, `health_checks`
- [ ] Set up PostgreSQL partitioning
- [ ] Create BRIN indexes
- [ ] Write rollback migration

**Day 3-4: Metrics Collection Service**
- [ ] Docker Stats API integration (`MetricsCollector`)
- [ ] Stats parsing (CPU, memory, disk, network)
- [ ] System metrics collection (psutil)
- [ ] Redis pub/sub broadcasting
- [ ] Database persistence

**Day 5-7: Celery Tasks & Scheduling**
- [ ] Container metrics task (5s interval)
- [ ] System metrics task (30s interval)
- [ ] Redis listener for broadcasting
- [ ] Test collection pipeline end-to-end

### Week 11: WebSocket & Alerting

**Day 1-2: WebSocket Server**
- [ ] Socket.IO server setup
- [ ] Connection management
- [ ] Subscribe/unsubscribe handlers
- [ ] Redis pub/sub → WebSocket bridge
- [ ] Integration with FastAPI

**Day 3-4: Alert System**
- [ ] Alert rule CRUD API
- [ ] Rule evaluation engine
- [ ] Alert lifecycle (fired → acknowledged → resolved)
- [ ] Notification dispatch (in-app, email stub, webhook stub)

**Day 5-6: Health Checks**
- [ ] Container health check polling
- [ ] Health status tracking
- [ ] Auto-restart on failure
- [ ] Health history API

**Day 7: REST API Completion**
- [ ] Metrics query endpoints
- [ ] Global/user/server metrics
- [ ] Alert history with filtering
- [ ] Health summary endpoint
- [ ] API testing

### Week 12: Frontend Dashboard

**Day 1-2: WebSocket Client**
- [ ] `useMetricsSocket` hook
- [ ] Connection management with auto-reconnect
- [ ] Metric data buffering
- [ ] Integration with Zustand store

**Day 3-4: Dashboard Components**
- [ ] Global metrics overview cards
- [ ] Server metrics real-time charts (Recharts)
- [ ] System metrics charts
- [ ] Connection status indicators

**Day 5-6: Alert & Health UI**
- [ ] Alert history table
- [ ] Alert rule management (admin)
- [ ] Health status grid
- [ ] Alert acknowledgment UI

**Day 7: Integration & Polish**
- [ ] Sidebar navigation updates
- [ ] Admin monitoring page
- [ ] User usage page
- [ ] Error boundaries and loading states
- [ ] End-to-end testing

---

## Deliverables

### Backend
- [ ] Metrics collection service (Docker Stats API)
- [ ] Time-series database schema with partitioning
- [ ] WebSocket server (Socket.IO) for real-time streaming
- [ ] Alert rule engine with evaluation
- [ ] Health check service with auto-restart
- [ ] REST API for metrics queries
- [ ] Celery tasks for scheduled collection

### Frontend
- [ ] WebSocket client hook with auto-reconnect
- [ ] Real-time metrics charts (CPU, memory, network)
- [ ] Global resource overview dashboard (admin)
- [ ] Per-user resource usage page
- [ ] Alert management UI (admin)
- [ ] Health status visualization
- [ ] Connection status indicators

### Infrastructure
- [ ] Celery beat schedule for metrics collection
- [ ] Redis pub/sub for metric broadcasting
- [ ] Database partitioning for performance
- [ ] Metrics retention policy (30 days)

---

## Success Criteria

```gherkin
Given a server is running
When I open the monitoring dashboard
Then I see CPU and memory usage updating every 5 seconds
And the charts show real-time data

Given I am an admin
When I view the global metrics page
Then I see total running servers, avg CPU, avg memory, and network I/O
And the data refreshes automatically

Given an alert rule is configured for CPU > 90%
When a server's CPU exceeds 90% for 60 seconds
Then an alert is created
And it appears in the alert history

Given a container fails its health check 3 times in a row
When the third failure occurs
Then the container is automatically restarted
And the restart is logged in health checks

Given I am a regular user
When I view my usage page
Then I see my servers' resource consumption
And I can view per-server real-time metrics
```

---

## Risk Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| High-frequency DB writes | High | High | Use batch inserts, connection pooling, partitioning |
| WebSocket memory leaks | High | Medium | Proper cleanup on disconnect, connection limits |
| Docker Stats API latency | Medium | Medium | Async collection, timeout handling, graceful degradation |
| Alert fatigue | Medium | Medium | Cooldown periods, grouping, severity levels |
| Metrics storage growth | Medium | High | Automated retention, compression, aggregation |
| Network partition (WS disconnect) | Medium | Medium | Auto-reconnect, buffer recent metrics |
| GPU metrics unavailable | Low | High | Graceful fallback, skip GPU fields |

---

## Dependencies

### Internal (from previous phases)
- [x] Docker/Podman socket access
- [x] PostgreSQL with partitioning support
- [x] Redis for pub/sub
- [x] FastAPI with async endpoints
- [x] Celery workers and beat scheduler
- [x] Server lifecycle (spawn/start/stop/delete)
- [x] RBAC system
- [x] Frontend with Zustand + Recharts

### External (new)
- [ ] `python-socketio` for WebSocket server
- [ ] `psutil` for host-level metrics
- [ ] WebSocket client (native browser API)

---

## Next Phase

**Phase 5: Advanced Platform Features** (Weeks 13-16)
- Audit logging with tamper-evident storage
- Server scheduling (cron-based start/stop)
- API key management with scopes
- Shared workspaces
- Advanced notifications (webhooks, email templates)
- Maintenance mode

---

**Document Version**: 1.0  
**Last Updated**: April 29, 2026  
**Author**: NukeLab Development Team
