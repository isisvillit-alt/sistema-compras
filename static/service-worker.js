self.addEventListener(
    "install",
    function () {
        self.skipWaiting();
    }
);

self.addEventListener(
    "activate",
    function (event) {
        event.waitUntil(
            (async function () {
                const nombresCache =
                    await caches.keys();

                await Promise.all(
                    nombresCache.map(
                        function (nombre) {
                            return caches.delete(
                                nombre
                            );
                        }
                    )
                );

                await self.registration.unregister();

                const ventanas =
                    await self.clients.matchAll(
                        {
                            type: "window",
                            includeUncontrolled: true
                        }
                    );

                ventanas.forEach(
                    function (ventana) {
                        ventana.navigate(
                            ventana.url
                        );
                    }
                );
            })()
        );
    }
);

/*
El service worker se desinstala y elimina
las versiones antiguas guardadas.
*/