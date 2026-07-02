# NukeLab Monitoring & Observability

NukeLab ships with an optional Prometheus + Grafana observability stack. It is
designed to replace high-volume DB request-metrics writes with a scrapable
metrics pipeline, making load tests and production monitoring cheaper and
faster.

---

## Quick Start

1. Copy and edit your environment file:

   ```bash
   cp .env.example .env
   ```

2. Enable monitoring in `.env`:

   ```env
   PROMETHEUS_ENABLED=true
   GRAFANA_ENABLED=true
   REQUEST_METRICS_STORE=prometheus   # or "both" to keep DB metrics too
   ```

3. Start the stack. `nukelabctl` auto-detects the monitoring overlay:

   ```bash
   ./nukelabctl start
   ```

   Or explicitly:

   ```bash
   ./nukelabctl start --overlay compose.monitoring.yml
   ```

4. Open the UIs:

   | Service     | URL                        | Default credentials          |
   |-------------|----------------------------|------------------------------|
   | Prometheus  | <http://localhost:9090>      | —                            |
   | Grafana     | <http://localhost:3001>      | admin / `GRAFANA_ADMIN_PASSWORD` |

---

## Architecture

```
+-------------+  scrape  +-------------+  query  +---------+
|  FastAPI    |--------->|  Prometheus |<--------| Grafana |
| /api/metrics|   15s    |   :9090     |         |  :3001  |
+-------------+          +-------------+         +---------+
        ^                        ^
        | scrape                 | scrape
        v                        v
+-------------+          +-------------+
| postgres-   |          | redis-      |
| exporter    |          | exporter    |
+-------------+          +-------------+
```

When `PGBOUNCER_ENABLED=true`, `nukelabctl` also adds the PgBouncer exporter
overlay (`compose.monitoring-pgbouncer.yml`).

---

## Backend Metrics

The backend exposes application-level metrics at `/api/metrics` when
`PROMETHEUS_ENABLED=true`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `nukelab_http_requests_total` | Counter | `method`, `path`, `status_code` | Total HTTP requests |
| `nukelab_http_request_duration_seconds` | Histogram | `method`, `path` | Request latency distribution |
| `nukelab_active_websocket_connections` | Gauge | — | Current WebSocket connections |
| `nukelab_redis_cache_hits_total` | Counter | — | Redis cache hits |
| `nukelab_redis_cache_misses_total` | Counter | — | Redis cache misses |
| `nukelab_users_total` | Gauge | — | Registered users |
| `nukelab_servers_total` | Gauge | `status` | Servers by status |
| `nukelab_nuke_balance_total` | Gauge | — | Total NUKE balance across users |

Business gauges (`users_total`, `servers_total`, `nuke_balance_total`) are
refreshed every 60 seconds by the Celery Beat task
`update-prometheus-business-metrics`.

---

## Grafana Dashboards

Two dashboards are provisioned automatically:

- **NukeLab API Performance** (`nukelab-api`)
  RPS, error rate, p50/p95/p99 latency, status-code breakdown, top slowest
  endpoints, WebSocket connections, Redis cache hit ratio.

- **NukeLab Infrastructure** (`nukelab-infrastructure`)
  Backend memory, Postgres connections/transactions, Redis memory/clients,
  business metrics, Celery throughput.

They appear under *Dashboards → Browse* after Grafana starts.

---

## Distributed Tracing (OpenTelemetry + Jaeger)

NukeLab supports end-to-end distributed tracing across FastAPI, Celery,
SQLAlchemy, and Redis via OpenTelemetry. Traces are exported in OTLP format to
an OpenTelemetry Collector, which forwards them to Jaeger for visualization.
Tracing is **disabled by default** to avoid runtime overhead.

### Enable tracing

```env
TRACING_ENABLED=true
OTEL_TRACES_ENABLED=true
```

`nukelabctl` auto-injects `compose.tracing.yml` when `TRACING_ENABLED=true`.

### Architecture

```
+----------+  OTLP/gRPC   +---------------+  OTLP/gRPC   +---------+
| FastAPI  |------------->| OTel Collector|------------->| Jaeger  |
| Celery   |              | :4317 / :4318 |              | :16686  |
+----------+              +---------------+              +---------+
                                                               |
                                                               v
                                                         +---------+
                                                         | Grafana |
                                                         | (Jaeger |
                                                         |  ds)    |
                                                         +---------+
```

### Access the UIs

| Service | URL                     | Notes |
|---------|-------------------------|-------|
| Jaeger  | <http://localhost:8080/jaeger> | Traefik ForwardAuth (admin login) |
| Grafana | <http://localhost:3001>    | Jaeger datasource provisioned automatically |

### Trace context propagation

- HTTP requests receive a `traceparent` response header when tracing is active.
- The existing `X-Correlation-ID` header continues to work; when no explicit
  correlation ID is provided, the OTel trace ID is used for log correlation.
- Celery tasks inherit the producer's trace context automatically.

### PII policy

Only `enduser.id` and `enduser.role` are attached to spans, matching the
existing Sentry scrubbing policy. Usernames and emails are never included in
trace attributes.

### Production alternatives

Replace the Jaeger exporter in `monitoring/otel/otel-collector.yml` with any
OTLP-compatible backend (Grafana Tempo, AWS X-Ray, Datadog, Honeycomb, etc.).
No application changes are required.

---

## Controlling Request Metrics Storage

The `REQUEST_METRICS_STORE` setting controls where per-request telemetry goes:

| Value | Behavior |
|-------|----------|
| `db` | Write to the Postgres `request_metrics` table only |
| `prometheus` | Export to `/api/metrics` only; DB table does not grow |
| `both` | Write to both Postgres and Prometheus (default) |

For large load tests, use `prometheus` to avoid the 6M+ row table growth that
skewed earlier benchmarks.

---

## Configuration Reference

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `PROMETHEUS_ENABLED` | `false` | Enable `/api/metrics` and the Prometheus container |
| `PROMETHEUS_PORT` | `9090` | Host port for Prometheus UI |
| `PROMETHEUS_RETENTION_TIME` | `15d` | TSDB retention |
| `GRAFANA_ENABLED` | `false` | Enable the Grafana container |
| `GRAFANA_PORT` | `3001` | Host port for Grafana UI |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana admin login |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `REQUEST_METRICS_ENABLED` | `true` | Enable the request metrics middleware |
| `REQUEST_METRICS_STORE` | `both` | `db` \| `prometheus` \| `both` |
| `POSTGRES_EXPORTER_ENABLED` | `true` | Enable postgres-exporter (when monitoring active) |
| `REDIS_EXPORTER_ENABLED` | `true` | Enable redis-exporter (when monitoring active) |

---

## Verifying the Stack

1. Check the Prometheus targets page:
   <http://localhost:9090/targets>
   `nukelab-backend` should be **UP**.

2. Scrape the metrics endpoint directly:

   ```bash
   curl -s http://localhost:8000/api/metrics | grep nukelab_http_requests_total
   ```

3. Run a load test and watch the dashboards:

   ```bash
   ./scripts/run-load-tests.sh baseline
   ```

---

## Adding Alerts

Grafana alerting can be configured through the UI or via provisioning files in
`monitoring/grafana/provisioning/alerting/`. A typical starting rule:

- **High error rate**: `rate(nukelab_http_requests_total{status_code=~"5.."}[1m]) /
  rate(nukelab_http_requests_total[1m]) > 0.05`

- **High p99 latency**: `histogram_quantile(0.99,
  sum(rate(nukelab_http_request_duration_seconds_bucket[5m])) by (le)) > 1.0`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `nukelab-backend` target DOWN in Prometheus | `PROMETHEUS_ENABLED=false` or backend not on `nukelab-network` | Enable in `.env` and restart |
| No data in Grafana dashboards | Prometheus not reachable | Check `PROMETHEUS_PORT` and Grafana datasource config |
| `request_metrics` table still growing | `REQUEST_METRICS_STORE=both` or `db` | Set to `prometheus` for load tests |
| Grafana dashboards missing | Provisioning path incorrect | Verify `monitoring/grafana/provisioning` is mounted read-only |

---

## Security

### 1. Protect the `/api/metrics` endpoint

By default the metrics endpoint has no authentication. For any environment where
Prometheus runs on a different host or the port is reachable by others, set a
scrape token:

```env
PROMETHEUS_SCRAPE_TOKEN=your-long-random-token
```

When this variable is non-empty, `/api/metrics` requires:

```
Authorization: Bearer your-long-random-token
```

The Prometheus scrape config automatically uses the same token.

### 2. Secure Grafana

- Change `GRAFANA_ADMIN_PASSWORD` from the default.
- Put Grafana behind Traefik with HTTPS in production.
- Disable public sign-ups (`GF_USERS_ALLOW_SIGN_UP=false` is already set).

### 3. Prometheus UI

In production, do not expose Prometheus port `9090` publicly. Access it through
a VPN, SSH tunnel, or an authenticated reverse proxy.

---

## Alertmanager (Optional)

Enable Alertmanager for notifications:

```env
ALERTMANAGER_ENABLED=true
```

Then restart:

```bash
./nukelabctl start
```

Alertmanager will be available at `http://localhost:9093`.

The generated config (`monitoring/alertmanager/alertmanager.generated.yml`) is
produced from `monitoring/alertmanager/alertmanager.yml.tpl` by `nukelabctl`.
Adjust environment variables (e.g., `ALERTMANAGER_EMAIL_TO`, `SMTP_*`) or edit
the template to change receivers (Slack, PagerDuty, email, Discord, etc.).

Included alert rules live in `monitoring/prometheus/rules/nukelab.yml`:

| Alert | Trigger |
|-------|---------|
| `NukeLabHighErrorRate` | 5xx rate > 5% for 2 minutes |
| `NukeLabHighLatency` | p99 latency > 1s for 3 minutes |
| `NukeLabTargetDown` | backend scrape target down for 1 minute |
| `NukeLabPostgresConnectionsHigh` | Postgres connections > 80% of max |
| `NukeLabRedisMemoryHigh` | Redis memory > 85% of max |

---

## Path to k3s / Kubernetes

The compose-based stack is intentionally simple for single-host deployments.
When you move to k3s, the same instrumentation works without changes:

1. Keep the `/api/metrics` endpoint and `prometheus-client` metrics in the app.
2. Replace the compose monitoring overlay with **kube-prometheus-stack**
   (Prometheus Operator).
3. Add a `ServiceMonitor` that scrapes the backend service on `/api/metrics`.
4. Re-use the dashboard JSON files by importing them into Grafana or mounting
   them as ConfigMaps.
5. Move alert rules from `monitoring/prometheus/rules/nukelab.yml` into
   PrometheusRule CRDs.

### Reusable assets for k3s

| Compose asset | k3s equivalent |
|---------------|----------------|
| `compose.monitoring.yml` | `kube-prometheus-stack` Helm chart |
| `compose.alertmanager.yml` | Alertmanager managed by the Operator |
| `monitoring/prometheus/prometheus.yml.tpl` | `ServiceMonitor` + `Prometheus` CRD |
| `monitoring/prometheus/rules/nukelab.yml` | `PrometheusRule` CRD |
| `monitoring/grafana/provisioning/dashboards/*.json` | Grafana dashboard ConfigMap |
| `PROMETHEUS_SCRAPE_TOKEN` | Network policies or ServiceMonitor auth |

For high-availability and long-term retention, add `remote_write` to
Thanos, Mimir, Cortex, or Grafana Cloud.

---

## Backup & Retention

Prometheus stores TSDB data in the `nukelab-prometheus-data` volume. Grafana
stores dashboards, users, and annotations in `nukelab-grafana-data`.

Back up both volumes regularly:

```bash
podman volume export nukelab-prometheus-data -o prometheus-backup.tar
podman volume export nukelab-grafana-data -o grafana-backup.tar
```

Control retention with:

```env
PROMETHEUS_RETENTION_TIME=30d
```

For longer retention or multi-node storage, use `remote_write` to external
object storage.
