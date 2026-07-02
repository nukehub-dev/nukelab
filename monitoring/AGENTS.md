# Monitoring

## Purpose

Observability stack configuration: Prometheus metrics, Grafana dashboards, Alertmanager routing, Jaeger tracing, and OpenTelemetry collector.

## Ownership

All files under `monitoring/`.

## Local Contracts

- Prometheus/Alertmanager configs are authored as `*.yml.tpl` templates and rendered to `*.generated.yml` by scripts in `scripts/`.
- Alert rules live in `prometheus/rules/nukelab.yml`.
- OTEL collector config lives in `otel/otel-collector.yml`.
- Jaeger config lives in `jaeger/jaeger.yml`.

## Work Guidance

- Edit `*.yml.tpl` files, then regenerate generated configs; do not hand-edit `*.generated.yml`.
- Add or update alert rules in `prometheus/rules/nukelab.yml`; guard expressions against division-by-zero and missing labels.
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
