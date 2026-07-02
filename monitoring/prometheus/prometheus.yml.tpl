global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Alertmanager is optional; enable by adding compose.alertmanager.yml.
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - /etc/prometheus/rules/*.yml

scrape_configs:
  - job_name: 'nukelab-backend'
    static_configs:
      - targets: ['backend:8000']
    metrics_path: /api/metrics
    scheme: http

  - job_name: 'postgres-exporter'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['redis-exporter:9121']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'celery-exporter'
    static_configs:
      - targets: ['celery-exporter:9808']

${PGBOUNCER_SCRAPE_JOBS}
