const CACHE_NAME = '__CACHE_NAME__';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/offline.html',
  '/manifest.json',
  '/favicon.svg',
  '/icon-192x192.png',
  '/icon-512x512.png',
  '/fonts/GeistVariable.woff2',
];

// Routes that must never be intercepted by the service worker.
// These are served by Traefik (Grafana/Prometheus/Alertmanager/Jaeger) or are API/WebSocket paths.
const BYPASS_PATHS = ['/api/', '/ws/', '/grafana', '/prometheus', '/alertmanager', '/jaeger'];

function shouldBypass(request, url) {
  if (request.method !== 'GET') return true;
  // Cross-origin requests should be handled by the browser.
  if (url.origin !== self.location.origin) return true;
  const pathname = url.pathname;
  for (const prefix of BYPASS_PATHS) {
    if (pathname.startsWith(prefix)) return true;
  }
  return false;
}

// Install: cache the static shell and offline page
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(cacheNames.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first navigation, cache-first static assets, bypass monitoring/API routes
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (shouldBypass(request, url)) return;

  // Navigation requests (page loads): network first, then cached shell, then offline page
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/index.html', clone));
          }
          return response;
        })
        .catch(() =>
          caches.match('/index.html').then((cached) => cached || caches.match('/offline.html'))
        )
    );
    return;
  }

  // Static assets (JS/CSS/images/fonts): stale-while-revalidate / cache first
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          if (response.status === 200 && response.type === 'basic') {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);

      return cached || networkFetch;
    })
  );
});
