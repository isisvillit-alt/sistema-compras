const OFFLINE_DB_NAME = "sistema_compras_offline";
const OFFLINE_DB_VERSION = 1;
const OFFLINE_STORE_NAME = "compras_pendientes";


function abrirBaseOffline() {
    return new Promise((resolve, reject) => {
        const solicitud = indexedDB.open(
            OFFLINE_DB_NAME,
            OFFLINE_DB_VERSION
        );

        solicitud.onupgradeneeded = function (evento) {
            const base = evento.target.result;

            if (
                !base.objectStoreNames.contains(
                    OFFLINE_STORE_NAME
                )
            ) {
                const almacen = base.createObjectStore(
                    OFFLINE_STORE_NAME,
                    {
                        keyPath: "sync_id"
                    }
                );

                almacen.createIndex(
                    "fecha_creacion",
                    "fecha_creacion",
                    {
                        unique: false
                    }
                );
            }
        };

        solicitud.onsuccess = function () {
            resolve(solicitud.result);
        };

        solicitud.onerror = function () {
            reject(
                solicitud.error
                || new Error(
                    "No se pudo abrir el almacenamiento local"
                )
            );
        };

        solicitud.onblocked = function () {
            reject(
                new Error(
                    "La base local está bloqueada"
                )
            );
        };
    });
}


async function guardarCompraPendiente(compra) {
    const base = await abrirBaseOffline();

    return new Promise((resolve, reject) => {
        const transaccion = base.transaction(
            OFFLINE_STORE_NAME,
            "readwrite"
        );

        const almacen = transaccion.objectStore(
            OFFLINE_STORE_NAME
        );

        almacen.put(compra);

        transaccion.oncomplete = function () {
            base.close();
            resolve();
        };

        transaccion.onerror = function () {
            const error = transaccion.error;

            base.close();

            reject(
                error
                || new Error(
                    "No se pudo guardar la compra pendiente"
                )
            );
        };

        transaccion.onabort = function () {
            const error = transaccion.error;

            base.close();

            reject(
                error
                || new Error(
                    "Se canceló el guardado local"
                )
            );
        };
    });
}


async function obtenerComprasPendientes() {
    const base = await abrirBaseOffline();

    return new Promise((resolve, reject) => {
        const transaccion = base.transaction(
            OFFLINE_STORE_NAME,
            "readonly"
        );

        const almacen = transaccion.objectStore(
            OFFLINE_STORE_NAME
        );

        const solicitud = almacen.getAll();

        solicitud.onsuccess = function () {
            const compras = solicitud.result || [];

            compras.sort((a, b) => {
                return (
                    a.fecha_creacion
                    || ""
                ).localeCompare(
                    b.fecha_creacion
                    || ""
                );
            });

            resolve(compras);
        };

        solicitud.onerror = function () {
            reject(
                solicitud.error
                || new Error(
                    "No se pudieron consultar "
                    + "las compras pendientes"
                )
            );
        };

        transaccion.oncomplete = function () {
            base.close();
        };
    });
}


async function eliminarCompraPendiente(syncId) {
    const base = await abrirBaseOffline();

    return new Promise((resolve, reject) => {
        const transaccion = base.transaction(
            OFFLINE_STORE_NAME,
            "readwrite"
        );

        const almacen = transaccion.objectStore(
            OFFLINE_STORE_NAME
        );

        almacen.delete(syncId);

        transaccion.oncomplete = function () {
            base.close();
            resolve();
        };

        transaccion.onerror = function () {
            const error = transaccion.error;

            base.close();

            reject(
                error
                || new Error(
                    "No se pudo eliminar "
                    + "la compra pendiente"
                )
            );
        };
    });
}


async function contarComprasPendientes() {
    const base = await abrirBaseOffline();

    return new Promise((resolve, reject) => {
        const transaccion = base.transaction(
            OFFLINE_STORE_NAME,
            "readonly"
        );

        const almacen = transaccion.objectStore(
            OFFLINE_STORE_NAME
        );

        const solicitud = almacen.count();

        solicitud.onsuccess = function () {
            resolve(solicitud.result || 0);
        };

        solicitud.onerror = function () {
            reject(
                solicitud.error
                || new Error(
                    "No se pudieron contar "
                    + "las compras pendientes"
                )
            );
        };

        transaccion.oncomplete = function () {
            base.close();
        };
    });
}


window.OfflineDB = {
    guardarCompraPendiente,
    obtenerComprasPendientes,
    eliminarCompraPendiente,
    contarComprasPendientes
};
