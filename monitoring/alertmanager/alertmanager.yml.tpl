# Alertmanager configuration for NukeLab.
# This file is a template; run scripts/generate-alertmanager-config.sh to
# produce monitoring/alertmanager/alertmanager.generated.yml before starting
# Alertmanager.

global:
  smtp_smarthost: '${SMTP_HOST}:${SMTP_PORT}'
  smtp_from: '${ALERTMANAGER_FROM}'
  smtp_require_tls: ${SMTP_REQUIRE_TLS}
  smtp_auth_username: '${SMTP_USER}'
  smtp_auth_password: '${SMTP_PASSWORD}'
  resolve_timeout: 5m

templates:
  - '/etc/alertmanager/templates/*.tmpl'

# Root route: group alerts, then fan out to severity-specific routes.
route:
  receiver: 'default'
  group_by: ['alertname', 'severity', 'job', 'instance']
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    # Dead man's switch: expect this alert to always be firing.
    - matchers:
        - alertname = DeadMansSwitch
      receiver: 'deadman'
      group_wait: 0s
      repeat_interval: 5m
      continue: false

    # Critical alerts: page immediately, keep notifying every hour.
    - matchers:
        - severity = critical
      receiver: 'critical'
      group_wait: 0s
      group_interval: 1m
      repeat_interval: 1h
      continue: true

    # Warning alerts: less noisy.
    - matchers:
        - severity = warning
      receiver: 'warning'
      group_interval: 10m
      repeat_interval: 12h
      continue: true

    # Info alerts: webhook only, once a day.
    - matchers:
        - severity = info
      receiver: 'info'
      repeat_interval: 24h
      continue: true

# Inhibit warnings and infos while a critical alert for the same alertname
# and instance is already firing.
inhibit_rules:
  - source_matchers:
      - severity = critical
    target_matchers:
      - severity =~ warning|info
    equal: ['alertname', 'instance']

receivers:
  - name: 'default'
    email_configs:
      - to: '${ALERTMANAGER_EMAIL_TO}'
        send_resolved: true
        html: '{{ template "nukelab.email.html" . }}'
        headers:
          Subject: '{{ template "nukelab.alert.subject" . }}'

  - name: 'critical'
    email_configs:
      - to: '${ALERTMANAGER_EMAIL_TO}'
        send_resolved: true
        html: '{{ template "nukelab.email.html" . }}'
        headers:
          Subject: '[CRITICAL] {{ .GroupLabels.alertname }}'

  - name: 'warning'
    email_configs:
      - to: '${ALERTMANAGER_EMAIL_TO}'
        send_resolved: true
        html: '{{ template "nukelab.email.html" . }}'
        headers:
          Subject: '[WARNING] {{ .GroupLabels.alertname }}'

  - name: 'info'
    email_configs:
      - to: '${ALERTMANAGER_EMAIL_TO}'
        send_resolved: true
        html: '{{ template "nukelab.email.html" . }}'
        headers:
          Subject: '[INFO] {{ .GroupLabels.alertname }}'

  - name: 'deadman'
    webhook_configs:
      - url: '${ALERTMANAGER_DEADMAN_URL}'
