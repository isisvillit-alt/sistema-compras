const CACHE_NAME = "sistema-compras-offline-v2";

const CORE_ASSETS = [
    "/compras",
    "/static/manifest.json",
    "/static/js/offline-db.js"
];

const CDN_ASSETS = [
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
    "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css"
];


async function guardarRecurso(cache, url) {
    try {
        const solicitud = new Request(
            url,
            {
                cache: "reload",
                credentials: url.startsWith("/")
                    ? "same-origin"
                    : "omit"
            }
        );

        const respuesta = await fetch(solicitud);

        /*
         * Evita guardar la pantalla de inicio
         * de sesión como si fuera /compras.
         */
        if (
            url === "/compras"
            && new URL(respuesta.url).pathname !== "/compras"
        ) {
            return;
        }

        if (
            respuesta.ok
            || respuesta.type === "opaque"
        ) {
            await cache.put(
                solicitud,
                respuesta
            );
        }

    } catch (error) {
        console.warn(
            "No se pudo precargar:",
            url,
            error
        );
    }
}


self.addEventListener(
    "install",
    function (evento) {
        evento.waitUntil(
            caches.open(CACHE_NAME)
                .then(
                    async function (cache) {
                        const recursos = [
                            ...CORE_ASSETS,
                            ...CDN_ASSETS
                        ];

                        for (const recurso of recursos) {
                            await guardarRecurso(
                                cache,
                                recurso
                            );
                        }
                    }
                )
                .then(
                    function () {
                        return self.skipWaiting();
                    }
                )
        );
    }
);


self.addEventListener(
    "activate",
    function (evento) {
        evento.waitUntil(
            caches.keys()
                .then(
                    function (nombres) {
                        return Promise.all(
                            nombres.map(
                                function (nombre) {
                                    if (
                                        nombre.startsWith(
                                            "sistema-compras-"
                                        )
                                        && nombre !== CACHE_NAME
                                    ) {
                                        return caches.delete(
                                            nombre
                                        );
                                    }

                                    return Promise.resolve();
                                }
                            )
                        );
                    }
                )
                .then(
                    function () {
                        return self.clients.claim();
                    }
                )
        );
    }
);


async function navegacionConRespaldo(solicitud) {
    try {
        const respuesta = await fetch(solicitud);

        const rutaRespuesta = new URL(
            respuesta.url
        ).pathname;

        /*
         * Actualiza la copia de /compras cuando
         * la página se abra correctamente.
         */
        if (
            respuesta.ok
            && rutaRespuesta === "/compras"
        ) {
            const cache = await caches.open(
                CACHE_NAME
            );

            await cache.put(
                "/compras",
                respuesta.clone()
            );
        }

        return respuesta;

    } catch (error) {
        const respuestaGuardada =
            await caches.match(
                solicitud,
                {
                    ignoreSearch: true
                }
            );

        if (respuestaGuardada) {
            return respuestaGuardada;
        }

        const pantallaCompras =
            await caches.match("/compras");

        if (pantallaCompras) {
            return pantallaCompras;
        }

        return new Response(
            `
            <!DOCTYPE html>
            <html lang="es">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>Sin conexión</title>
            </head>

            <body>
                <main>
                    <h1>Sin conexión</h1>

                    <p>
                        Abre la aplicación una vez con
                        internet para preparar el modo
                        sin conexión.
                    </p>
                </main>
            </body>
            </html>
            `,
            {
                status: 503,
                headers: {
                    "Content-Type":
                        "text/html; charset=UTF-8"
                }
            }
        );
    }
}


async function recursoConCache(solicitud) {
    const guardado = await caches.match(
        solicitud
    );

    if (guardado) {
        return guardado;
    }

    const respuesta = await fetch(
        solicitud
    );

    if (
        respuesta.ok
        || respuesta.type === "opaque"
    ) {
        const cache = await caches.open(
            CACHE_NAME
        );

        await cache.put(
            solicitud,
            respuesta.clone()
        );
    }

    return respuesta;
}


self.addEventListener(
    "fetch",
    function (evento) {
        const solicitud = evento.request;

        if (solicitud.method !== "GET") {
            return;
        }

        const url = new URL(
            solicitud.url
        );

        /*
         * Las solicitudes de sincronización
         * siempre deben ir al servidor.
         */
        if (
            url.origin === self.location.origin
            && url.pathname.startsWith("/api/")
        ) {
            return;
        }

        if (solicitud.mode === "navigate") {
            evento.respondWith(
                navegacionConRespaldo(
                    solicitud
                )
            );

            return;
        }

        const esArchivoEstatico =
            url.origin === self.location.origin
            && (
                url.pathname.startsWith("/static/")
                || url.pathname === "/service-worker.js"
            );

        const esCDN =
            url.hostname === "cdn.jsdelivr.net"
            || url.hostname === "cdnjs.cloudflare.com";

        if (
            esArchivoEstatico
            || esCDN
        ) {
            evento.respondWith(
                recursoConCache(
                    solicitud
                )
            );
        }
    }
);
