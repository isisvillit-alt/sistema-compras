const CACHE_NAME = "compras-cache-v1";

const urlsToCache = [
  "/",
  "/login",
  "/compras",
  "/historial",
  "/static/manifest.json"
];

// INSTALACIÓN
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

// ACTIVACIÓN
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
});

// FETCH (ESTO ES LO IMPORTANTE)
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      // si existe en cache → lo devuelve
      if (response) return response;

      // si no → intenta red
      return fetch(event.request).catch(() => {
        // fallback opcional
        if (event.request.destination === "document") {
          return caches.match("/");
        }
      });
    })
  );
});
