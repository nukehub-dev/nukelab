/**
 * k6 API Stress Test — High-RPS endpoint hammering.
 *
 * k6 runs in a lightweight Go runtime, making it capable of much higher
 * RPS per CPU than Locust. Use this for pure endpoint stress testing.
 *
 * Usage:
 *   docker compose -f compose.loadtest.yml run --rm k6 run /scripts/api-stress.js
 *
 * Profiles (set via env var K6_PROFILE):
 *   smoke     → 10 VUs,  30s
 *   baseline  → 100 VUs, 5m
 *   stress    → 500 VUs, 10m
 *   spike     → 10→500 VUs, 5m
 *   endurance → 100 VUs, 30m
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const HOST = __ENV.K6_HOST || 'http://traefik:80';
const PROFILE = __ENV.K6_PROFILE || 'baseline';
const TEST_USER_COUNT = parseInt(__ENV.TEST_USER_COUNT || '100');

const errorRate = new Rate('errors');
const healthP95 = new Trend('health_p95');
const listServersP95 = new Trend('list_servers_p95');

const profiles = {
  smoke: {
    stages: [
      { duration: '30s', target: 10 },
      { duration: '10s', target: 0 },
    ],
    thresholds: {
      http_req_duration: ['p(95)<8000'],
      errors: ['rate<0.01'],
    },
  },
  baseline: {
    stages: [
      { duration: '1m', target: 100 },
      { duration: '5m', target: 100 },
      { duration: '1m', target: 0 },
    ],
    thresholds: {
      http_req_duration: ['p(95)<8000'],
      http_req_failed: ['rate<0.05'],
      errors: ['rate<0.05'],
    },
  },
  stress: {
    stages: [
      { duration: '2m', target: 100 },
      { duration: '5m', target: 500 },
      { duration: '5m', target: 500 },
      { duration: '2m', target: 0 },
    ],
    thresholds: {
      http_req_duration: ['p(95)<15000'],
      http_req_failed: ['rate<0.10'],
    },
  },
  spike: {
    stages: [
      { duration: '2m', target: 10 },
      { duration: '30s', target: 500 },
      { duration: '3m', target: 500 },
      { duration: '30s', target: 10 },
      { duration: '2m', target: 0 },
    ],
    thresholds: {
      http_req_duration: ['p(95)<20000'],
      http_req_failed: ['rate<0.20'],
    },
  },
  endurance: {
    stages: [
      { duration: '2m', target: 100 },
      { duration: '30m', target: 100 },
      { duration: '2m', target: 0 },
    ],
    thresholds: {
      http_req_duration: ['p(95)<10000'],
      http_req_failed: ['rate<0.05'],
    },
  },
};

export const options = profiles[PROFILE] || profiles.baseline;

const TEST_USERS = Array.from({ length: TEST_USER_COUNT }, (_, i) => ({
  username: `loadtest_${String(i).padStart(4, '0')}`,
  password: 'LoadTest123!',
}));

function pickUser() {
  return TEST_USERS[Math.floor(Math.random() * TEST_USERS.length)];
}

function login(username, password) {
  const resp = http.post(`${HOST}/api/auth/login`, {
    username: username,
    password: password,
  });

  const ok = check(resp, {
    'login status is 200': (r) => r.status === 200,
    'login returns token': (r) => r.json('access_token') !== undefined,
  });

  errorRate.add(!ok);
  return ok ? resp.json('access_token') : null;
}

// ── Token pool (pre-generated tokens from generate_tokens.py) ─────────────

let tokenPool = [];
try {
  const raw = open('/mnt/locust/tokens.json');
  const pool = JSON.parse(raw);
  tokenPool = Object.values(pool);
} catch (e) {
  // Token pool not available — will fall back to per-VU login
}

function getToken() {
  if (tokenPool.length > 0) {
    // Round-robin assign pre-generated tokens by VU id
    return tokenPool[__VU % tokenPool.length];
  }
  // Fallback: login on first use (slow, may hit rate limits)
  const user = pickUser();
  return login(user.username, user.password);
}

// ── Per-VU token cache ────────────────────────────────────────────────────

const vuTokens = {};

function ensureToken() {
  const vu = __VU;
  if (!vuTokens[vu]) {
    vuTokens[vu] = getToken();
  }
  return vuTokens[vu];
}

function clearToken() {
  delete vuTokens[__VU];
}

function makeRequest(method, url, body, headers, tags) {
  let resp;
  if (method === 'get') {
    resp = http.get(url, { headers, tags });
  } else if (method === 'post') {
    resp = http.post(url, body, { headers, tags });
  } else {
    resp = http.request(method.toUpperCase(), url, body, { headers, tags });
  }

  // If token expired, re-auth once and retry
  if (resp.status === 401) {
    clearToken();
    const newToken = ensureToken();
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`;
      if (method === 'get') {
        resp = http.get(url, { headers, tags });
      } else if (method === 'post') {
        resp = http.post(url, body, { headers, tags });
      } else {
        resp = http.request(method.toUpperCase(), url, body, { headers, tags });
      }
    }
  }
  return resp;
}

export default function () {
  const token = ensureToken();

  if (!token) {
    sleep(1);
    return;
  }

  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  const health = makeRequest('get', `${HOST}/api/system/health`, null, {}, { name: 'GET /health' });
  check(health, { 'health is 200': (r) => r.status === 200 });
  healthP95.add(health.timings.duration);
  errorRate.add(health.status !== 200);

  const servers = makeRequest('get', `${HOST}/api/servers`, null, headers, { name: 'GET /api/servers' });
  check(servers, { 'list servers is 200': (r) => r.status === 200 });
  listServersP95.add(servers.timings.duration);
  errorRate.add(servers.status !== 200);

  const me = makeRequest('get', `${HOST}/api/auth/me`, null, headers, { name: 'GET /api/auth/me' });
  check(me, { 'me is 200': (r) => r.status === 200 });
  errorRate.add(me.status !== 200);

  const credits = makeRequest('get', `${HOST}/api/credits/`, null, headers, { name: 'GET /api/credits/' });
  check(credits, { 'credits is 200': (r) => r.status === 200 });
  errorRate.add(credits.status !== 200);

  const envs = makeRequest('get', `${HOST}/api/environments/`, null, headers, { name: 'GET /api/environments' });
  check(envs, { 'environments is 200': (r) => r.status === 200 });
  errorRate.add(envs.status !== 200);

  sleep(Math.random() * 3 + 1);
}
