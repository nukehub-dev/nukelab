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
// These are served by Traefik (Grafana/Prometheus/Alertmanager/Jaeger), API/WebSocket paths,
// or per-server terminal routes that must reach the backend container directly.
const BYPASS_PATHS = ['/api/', '/ws/', '/user/', '/grafana', '/prometheus', '/alertmanager', '/jaeger'];

function shouldBypass(request, url) {
  if (request.method !== 'GET') return true;
  // Cross-origin requests should be handled by the browser.
  if (url.origin !== self.location.origin) return true;
  const pathname = url.pathname;
  for (const prefix of BYPASS_PATHS) {
    if (pathname.startsWith(prefix)) return true;
  }
  // Visualizer reverse-proxy routes are served by the IDE container's trame
  // servers and must not be served the cached SPA shell. They normally live
  // under /user/.../visualizer/, but bypass them anywhere they appear as a
  // defense-in-depth measure.
  if (pathname.includes('/visualizer/')) return true;
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

// Allow the SPA to force activation of a waiting service worker before
// navigating to a server environment. This prevents stale SWs from serving
// the cached SPA shell for /user/ routes.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Web Push: show a notification from the push payload.
self.addEventListener('push', (event) => {
  let payload = { title: 'NukeLab', body: '', action_url: '/' }
  try {
    if (event.data) {
      payload = event.data.json()
    }
  } catch {
    // Fall back to defaults.
  }

  const title = payload.title || 'NukeLab'
  const options = {
    body: payload.body || '',
    icon: '/icon-192x192.png',
    badge: '/icon-192x192.png',
    tag: payload.tag || payload.action_url || 'nukelab-notification',
    requireInteraction: false,
    data: {
      action_url: payload.action_url || '/',
    },
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

// Notification click: focus an existing client or open the deep link.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  const action_url = event.notification.data?.action_url || '/'
  // client.url is absolute; action_url is relative — compare by path+search.
  const targetUrl = new URL(action_url, self.location.origin)
  const targetPath = targetUrl.pathname + targetUrl.search

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // Prefer a tab already showing the target page.
        for (const client of clientList) {
          const clientUrl = new URL(client.url)
          if (clientUrl.pathname + clientUrl.search === targetPath && 'focus' in client) {
            return client.focus()
          }
        }
        // Otherwise reuse any open app tab and navigate it to the target.
        for (const client of clientList) {
          if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
            return client.focus().then((c) => (c && c.navigate ? c.navigate(targetUrl.href) : c))
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetPath)
        }
      })
  )
})

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
