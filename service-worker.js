self.addEventListener("install", event => {
  event.waitUntil(
    caches.open("compras-cache").then(cache => {
      return cache.addAll([
        "/",
        "/compras",
        "/historial",
        "/login"
      ]);
    })
  );
});