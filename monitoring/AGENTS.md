# Monitoring

## Purpose

Observability stack configuration: Prometheus metrics, Grafana dashboards, Alertmanager routing, Jaeger tracing, and OpenTelemetry collector.

## Ownership

All files under `monitoring/`.

## Local Contracts

- Prometheus/Alertmanager configs and alert rules are authored as `*.yml.tpl` templates and rendered by scripts in `scripts/`.
  - Configs render to `*.generated.yml`.
  - Alert rules render to `prometheus/rules/nukelab.generated.yml`.
- `NODE_EXPORTER_ROOTFS_PATH` (default `/host`) must stay in sync between `.env`, `compose.monitoring.yml`, and `prometheus/rules/nukelab.yml.tpl`. The Grafana dashboard uses a `node_exporter_rootfs_path` constant variable for the same purpose.
- OTEL collector config lives in `otel/otel-collector.yml`.
- Jaeger config lives in `jaeger/jaeger.yml`.

## Work Guidance

- Edit `*.yml.tpl` files, then regenerate generated configs and rules; do not hand-edit `*.generated.yml` or `prometheus/rules/nukelab.yml`.
- Add or update alert rules in `prometheus/rules/nukelab.yml.tpl`; guard expressions against division-by-zero and missing labels.
- Keep OTEL collector config aligned with backend tracing instrumentation in `backend/app/core/tracing.py`.
- Dashboard provisioning and datasource config are owned by Grafana files in `grafana/`.

## Verification

```bash
./nukelabctl lint shell   # validates generation scripts
# Regenerate configs and review generated output:
./scripts/generate-prometheus-config.sh
./scripts/generate-alertmanager-config.sh
```

## Child NAD Index

- None
