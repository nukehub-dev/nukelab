self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("nukelab-cache-v1").then((cache) => {
      return cache.addAll([
        "/",
        "/hub/static/manifest.json",
        "/hub/static/logo.svg",
        "/hub/static/logo.png",
      ]);
    })
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});
