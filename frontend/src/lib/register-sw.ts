/**
 * Register the NukeLab service worker in production builds.
 *
 * The service worker is intentionally disabled in development to avoid
 * intercepting Vite's HMR and serving stale assets. It also never intercepts
 * /api, /ws, /grafana, /prometheus, or /alertmanager.
 */
export function registerServiceWorker() {
  if (import.meta.env.DEV) return;
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        console.log('SW registered:', registration.scope);
      })
      .catch((error) => {
        console.error('SW registration failed:', error);
      });
  });
}
