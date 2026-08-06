import os
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import unquote, urlparse

import cloudinary
import cloudinary.uploader
import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from flask import (
    Flask,
    jsonify,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_mail import Mail, Message
from itsdangerous import (
    BadSignature,
    SignatureExpired,
    URLSafeTimedSerializer,
)
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)
from werkzeug.utils import secure_filename


# ==================================================
# FUNCIONES AUXILIARES
# ==================================================

def variable_obligatoria(nombre):
    valor = os.environ.get(nombre)

    if not valor:
        raise RuntimeError(
            f"Falta la variable de entorno: {nombre}"
        )

    return valor


def login_requerido(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if "user_id" not in session:
            return redirect(
                url_for("login")
            )

        return funcion(*args, **kwargs)

    return envoltura


def obtener_campo(*nombres):
    """
    Acepta nombres de formularios nuevos y antiguos.
    """

    for nombre in nombres:
        valor = request.form.get(nombre)

        if valor is not None:
            return str(valor).strip()

    return ""


def convertir_monto(texto):
    try:
        monto = Decimal(
            texto.replace(",", ".")
        )

        if not monto.is_finite():
            raise InvalidOperation

        monto = monto.quantize(
            Decimal("0.01")
        )

    except (
        InvalidOperation,
        AttributeError,
    ) as error:
        raise ValueError(
            "El monto no es válido"
        ) from error

    if monto < 0:
        raise ValueError(
            "El monto no puede ser negativo"
        )

    return monto


def convertir_fecha(texto):
    try:
        return datetime.strptime(
            texto,
            "%Y-%m-%d",
        ).date()

    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            "La fecha no es válida"
        ) from error


def limites_del_mes(clave_mes):
    try:
        inicio = datetime.strptime(
            clave_mes,
            "%Y-%m",
        ).date()

    except ValueError:
        abort(404)

    if inicio.month == 12:
        fin = inicio.replace(
            year=inicio.year + 1,
            month=1,
        )

    else:
        fin = inicio.replace(
            month=inicio.month + 1,
        )

    return inicio, fin


def nombre_mes(numero):
    nombres = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }

    return nombres[numero]


# ==================================================
# CONFIGURACIÓN DE FLASK
# ==================================================

app = Flask(__name__)

# Lee automáticamente CLOUDINARY_URL desde las variables
# de entorno configuradas en Render.
cloudinary.config(
    secure=True
)

app.secret_key = variable_obligatoria(
    "SECRET_KEY"
)

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Máximo 10 MB por evidencia
app.config["MAX_CONTENT_LENGTH"] = (
    10 * 1024 * 1024
)

serializer = URLSafeTimedSerializer(
    app.secret_key
)


@app.after_request
def evitar_cache(response):
    """
    Evita que Safari muestre formularios anteriores.
    """

    if request.endpoint != "static":
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, "
            "max-age=0"
        )

        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# ==================================================
# CORREO
# ==================================================

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True

app.config["MAIL_USERNAME"] = (
    os.environ.get("MAIL_USERNAME")
)

app.config["MAIL_PASSWORD"] = (
    os.environ.get("MAIL_PASSWORD")
)

mail = Mail(app)


# ==================================================
# POSTGRESQL / SUPABASE
# ==================================================

def get_db():
    return psycopg.connect(
        host=variable_obligatoria(
            "DB_HOST"
        ),
        port=int(
            os.environ.get(
                "DB_PORT",
                "5432",
            )
        ),
        dbname=os.environ.get(
            "DB_NAME",
            "postgres",
        ),
        user=variable_obligatoria(
            "DB_USER"
        ),
        password=variable_obligatoria(
            "DB_PASSWORD"
        ),
        sslmode="require",
        connect_timeout=10,
        row_factory=dict_row,
    )


# ==================================================
# EVIDENCIAS
# ==================================================

UPLOAD_FOLDER = os.path.join(
    app.root_path,
    "uploads",
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True,
)

app.config["UPLOAD_FOLDER"] = (
    UPLOAD_FOLDER
)

EXTENSIONES_PERMITIDAS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
    "pdf",
}


def archivo_permitido(nombre_archivo):
    if not nombre_archivo:
        return False

    if "." not in nombre_archivo:
        return False

    extension = (
        nombre_archivo
        .rsplit(".", 1)[1]
        .lower()
    )

    return extension in EXTENSIONES_PERMITIDAS


def guardar_evidencia(archivo):
    if (
        archivo is None
        or not archivo.filename
    ):
        raise ValueError(
            "Debes seleccionar una evidencia"
        )

    if not archivo_permitido(
        archivo.filename
    ):
        raise ValueError(
            "Solo se permiten archivos JPG, JPEG, "
            "PNG, WEBP o PDF"
        )

    nombre_seguro = secure_filename(
        archivo.filename
    )

    if not nombre_seguro:
        raise ValueError(
            "El nombre del archivo no es válido"
        )

    extension = (
        nombre_seguro
        .rsplit(".", 1)[1]
        .lower()
    )

    identificador = str(
        uuid.uuid4()
    )

    if extension == "pdf":
        tipo_recurso = "raw"
        public_id = (
            f"sistema-compras/"
            f"{identificador}.pdf"
        )

    else:
        tipo_recurso = "image"
        public_id = (
            f"sistema-compras/"
            f"{identificador}"
        )

    archivo.stream.seek(0)

    resultado = cloudinary.uploader.upload(
        archivo.stream,
        resource_type=tipo_recurso,
        public_id=public_id,
        overwrite=False,
    )

    evidencia_url = resultado.get(
        "secure_url"
    )

    if not evidencia_url:
        raise RuntimeError(
            "Cloudinary no devolvió la URL "
            "de la evidencia"
        )

    return evidencia_url


def obtener_datos_cloudinary(evidencia):
    if not evidencia:
        return None

    if not evidencia.startswith(
        ("http://", "https://")
    ):
        return None

    url = urlparse(
        evidencia
    )

    if url.netloc != "res.cloudinary.com":
        return None

    partes = [
        unquote(parte)
        for parte in url.path.split("/")
        if parte
    ]

    try:
        indice_upload = partes.index(
            "upload"
        )

    except ValueError:
        return None

    if indice_upload < 1:
        return None

    tipo_recurso = partes[
        indice_upload - 1
    ]

    if tipo_recurso not in {
        "image",
        "raw",
        "video",
    }:
        return None

    partes_public_id = partes[
        indice_upload + 1:
    ]

    if (
        partes_public_id
        and re.fullmatch(
            r"v\d+",
            partes_public_id[0],
        )
    ):
        partes_public_id = (
            partes_public_id[1:]
        )

    public_id = "/".join(
        partes_public_id
    )

    if (
        tipo_recurso == "image"
        and "." in public_id
    ):
        public_id = public_id.rsplit(
            ".",
            1,
        )[0]

    if not public_id:
        return None

    return tipo_recurso, public_id


def borrar_evidencia(evidencia):
    if not evidencia:
        return

    datos_cloudinary = (
        obtener_datos_cloudinary(
            evidencia
        )
    )

    if datos_cloudinary:
        tipo_recurso, public_id = (
            datos_cloudinary
        )

        try:
            cloudinary.uploader.destroy(
                public_id,
                resource_type=tipo_recurso,
                invalidate=True,
            )

        except Exception:
            app.logger.exception(
                "No se pudo borrar la evidencia "
                "de Cloudinary"
            )

        return

    # Compatibilidad con archivos antiguos guardados
    # localmente antes de utilizar Cloudinary.
    ruta_archivo = os.path.join(
        app.config["UPLOAD_FOLDER"],
        evidencia,
    )

    if os.path.exists(ruta_archivo):
        try:
            os.remove(
                ruta_archivo
            )

        except OSError:
            app.logger.exception(
                "No se pudo borrar la evidencia local"
            )


@app.route(
    "/uploads/<path:nombre_archivo>"
)
@login_requerido
def mostrar_archivo(nombre_archivo):
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM compras
                    WHERE evidencia = %s
                      AND user_id = %s
                    LIMIT 1
                    """,
                    (
                        nombre_archivo,
                        session["user_id"],
                    ),
                )

                existe = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error consultando evidencia"
        )

        return (
            "No se pudo consultar la evidencia",
            500,
        )

    if not existe:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        nombre_archivo,
    )


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
    )

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, "
        "max-age=0"
    )

    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Service-Worker-Allowed"] = "/"

    return response


# ==================================================
# LOGIN
# ==================================================

@app.route("/")
def login():
    if "user_id" in session:
        return redirect(
            url_for("compras")
        )

    return render_template(
        "login.html"
    )


@app.route(
    "/validar",
    methods=["POST"],
)
def validar():
    acceso = (
        request.form.get("email")
        or request.form.get("correo")
        or request.form.get("usuario")
        or ""
    ).strip().lower()

    password = request.form.get(
        "password",
        "",
    )

    if not acceso or not password:
        return (
            "Debes escribir correo y contraseña",
            400,
        )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        usuario,
                        email,
                        password
                    FROM usuarios
                    WHERE LOWER(email) = %s
                       OR LOWER(usuario) = %s
                    LIMIT 1
                    """,
                    (
                        acceso,
                        acceso,
                    ),
                )

                usuario = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error consultando usuario"
        )

        return (
            "No se pudo conectar con la base de datos",
            500,
        )

    if (
        usuario
        and check_password_hash(
            usuario["password"],
            password,
        )
    ):
        session.clear()

        session["user_id"] = (
            usuario["id"]
        )

        session["usuario"] = (
            usuario["usuario"]
        )

        return redirect(
            url_for("compras")
        )

    return (
        "Correo o contraseña incorrectos",
        401,
    )


@app.route("/salir")
def salir():
    session.clear()

    return redirect(
        url_for("login")
    )


# ==================================================
# REGISTRAR COMPRA
# ==================================================

@app.route("/compras")
@login_requerido
def compras():
    return render_template(
        "compras.html",
        fecha_hoy=(
            datetime.now()
            .date()
            .isoformat()
        ),
    )


@app.route(
    "/guardar",
    methods=["POST"],
)
@login_requerido
def guardar():
    producto = obtener_campo(
        "producto",
        "product",
        "nombre_producto",
    )

    proveedor = obtener_campo(
        "proveedor",
        "provider",
    )

    cliente = obtener_campo(
        "cliente",
        "client",
        "nombre_cliente",
    )

    monto_texto = obtener_campo(
        "monto",
        "amount",
    )

    fecha_texto = obtener_campo(
        "fecha",
        "date",
    )

    if not producto:
        app.logger.warning(
            "Formulario sin producto. Campos: %s",
            list(request.form.keys()),
        )

        return (
            "No se recibió el producto. "
            "Cierra y vuelve a abrir la aplicación.",
            400,
        )

    if not proveedor:
        return (
            "Debes escribir el proveedor",
            400,
        )

    try:
        monto = convertir_monto(
            monto_texto
        )

        fecha = convertir_fecha(
            fecha_texto
        )

        evidencia_url = guardar_evidencia(
            request.files.get("foto")
            or request.files.get("evidencia")
        )

    except ValueError as error:
        return str(error), 400

    except Exception:
        app.logger.exception(
            "Error guardando evidencia"
        )

        return (
            "No se pudo guardar la evidencia",
            500,
        )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO compras (
                        producto,
                        proveedor,
                        cliente,
                        monto,
                        fecha,
                        evidencia,
                        user_id,
                        eliminado
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        FALSE
                    )
                    """,
                    (
                        producto,
                        proveedor,
                        cliente or None,
                        monto,
                        fecha,
                        evidencia_url,
                        session["user_id"],
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error guardando compra"
        )

        borrar_evidencia(
            evidencia_url
        )

        return (
            "No se pudo guardar la compra",
            500,
        )

    return redirect(
        url_for(
            "historial_dia",
            fecha=fecha.isoformat(),
        )
    )


# ==================================================
# HISTORIAL PRINCIPAL
# ==================================================

@app.route("/historial")
@login_requerido
def historial():
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM compras
                    WHERE user_id = %s
                      AND eliminado = FALSE
                    """,
                    (
                        session["user_id"],
                    ),
                )

                resumen = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error cargando historial"
        )

        return (
            "No se pudo cargar el historial",
            500,
        )

    return render_template(
        "historial.html",
        total_compras=resumen["total"],
    )


# ==================================================
# CARPETAS DE MESES
# ==================================================

@app.route("/historial/meses")
@login_requerido
def historial_meses():
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        EXTRACT(YEAR FROM fecha)::INTEGER
                            AS anio,

                        EXTRACT(MONTH FROM fecha)::INTEGER
                            AS mes,

                        COUNT(*) AS cantidad,

                        COALESCE(
                            SUM(monto),
                            0
                        ) AS total

                    FROM compras

                    WHERE user_id = %s
                      AND eliminado = FALSE

                    GROUP BY
                        EXTRACT(YEAR FROM fecha),
                        EXTRACT(MONTH FROM fecha)

                    ORDER BY
                        anio DESC,
                        mes DESC
                    """,
                    (
                        session["user_id"],
                    ),
                )

                resultados = cursor.fetchall()

    except Exception:
        app.logger.exception(
            "Error cargando meses"
        )

        return (
            "No se pudieron cargar los meses",
            500,
        )

    meses = []

    for resultado in resultados:
        meses.append(
            {
                "clave": (
                    f"{resultado['anio']:04d}-"
                    f"{resultado['mes']:02d}"
                ),
                "nombre": (
                    f"{nombre_mes(resultado['mes'])} "
                    f"{resultado['anio']}"
                ),
                "cantidad": resultado["cantidad"],
                "total": resultado["total"],
            }
        )

    return render_template(
        "historial_meses.html",
        meses=meses,
    )


# ==================================================
# CARPETAS DE DÍAS
# ==================================================

@app.route(
    "/historial/mes/<clave_mes>"
)
@login_requerido
def historial_mes(clave_mes):
    inicio, fin = limites_del_mes(
        clave_mes
    )

    titulo_mes = (
        f"{nombre_mes(inicio.month)} "
        f"{inicio.year}"
    )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        fecha,
                        COUNT(*) AS cantidad,
                        COALESCE(
                            SUM(monto),
                            0
                        ) AS total

                    FROM compras

                    WHERE user_id = %s
                      AND eliminado = FALSE
                      AND fecha >= %s
                      AND fecha < %s

                    GROUP BY fecha

                    ORDER BY fecha DESC
                    """,
                    (
                        session["user_id"],
                        inicio,
                        fin,
                    ),
                )

                dias = cursor.fetchall()

    except Exception:
        app.logger.exception(
            "Error cargando días"
        )

        return (
            "No se pudieron cargar los días",
            500,
        )

    return render_template(
        "historial_dias.html",
        dias=dias,
        titulo_mes=titulo_mes,
    )


# ==================================================
# COMPRAS DE UN DÍA
# ==================================================

@app.route(
    "/historial/dia/<fecha>"
)
@login_requerido
def historial_dia(fecha):
    try:
        fecha_compra = convertir_fecha(
            fecha
        )

    except ValueError:
        abort(404)

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        producto,
                        proveedor,
                        cliente,
                        monto,
                        fecha,
                        evidencia

                    FROM compras

                    WHERE user_id = %s
                      AND eliminado = FALSE
                      AND fecha = %s

                    ORDER BY id DESC
                    """,
                    (
                        session["user_id"],
                        fecha_compra,
                    ),
                )

                lista_compras = (
                    cursor.fetchall()
                )

    except Exception:
        app.logger.exception(
            "Error cargando compras del día"
        )

        return (
            "No se pudieron cargar las compras",
            500,
        )

    return render_template(
        "historial_compras.html",
        compras=lista_compras,
        titulo=fecha_compra.strftime(
            "%d/%m/%Y"
        ),
        subtitulo="Compras del día",
        volver_url=url_for(
            "historial_mes",
            clave_mes=fecha_compra.strftime(
                "%Y-%m"
            ),
        ),
    )


# ==================================================
# BÚSQUEDA
# ==================================================

@app.route("/historial/buscar")
@login_requerido
def historial_buscar():
    texto = request.args.get(
        "q",
        "",
    ).strip().lower()

    fecha_texto = request.args.get(
        "fecha",
        "",
    ).strip()

    condiciones = [
        "user_id = %s",
        "eliminado = FALSE",
    ]

    valores = [
        session["user_id"],
    ]

    if texto:
        patron = f"%{texto}%"

        condiciones.append(
            """
            (
                LOWER(producto) LIKE %s
                OR LOWER(proveedor) LIKE %s
                OR LOWER(
                    COALESCE(cliente, '')
                ) LIKE %s
            )
            """
        )

        valores.extend(
            [
                patron,
                patron,
                patron,
            ]
        )

    if fecha_texto:
        try:
            fecha_busqueda = (
                convertir_fecha(
                    fecha_texto
                )
            )

        except ValueError as error:
            return str(error), 400

        condiciones.append(
            "fecha = %s"
        )

        valores.append(
            fecha_busqueda
        )

    consulta = f"""
        SELECT
            id,
            producto,
            proveedor,
            cliente,
            monto,
            fecha,
            evidencia

        FROM compras

        WHERE {' AND '.join(condiciones)}

        ORDER BY fecha DESC, id DESC
    """

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    consulta,
                    tuple(valores),
                )

                lista_compras = (
                    cursor.fetchall()
                )

    except Exception:
        app.logger.exception(
            "Error buscando compras"
        )

        return (
            "No se pudo realizar la búsqueda",
            500,
        )

    return render_template(
        "historial_compras.html",
        compras=lista_compras,
        titulo="Resultados",
        subtitulo=(
            "Producto, proveedor, cliente o fecha"
        ),
        volver_url=url_for(
            "historial"
        ),
    )


# ==================================================
# EDITAR COMPRA
# ==================================================

@app.route(
    "/editar/<int:id>",
    methods=["GET", "POST"],
)
@login_requerido
def editar_compra(id):
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        producto,
                        proveedor,
                        cliente,
                        monto,
                        fecha,
                        evidencia

                    FROM compras

                    WHERE id = %s
                      AND user_id = %s
                      AND eliminado = FALSE

                    LIMIT 1
                    """,
                    (
                        id,
                        session["user_id"],
                    ),
                )

                compra = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error consultando compra"
        )

        return (
            "No se pudo consultar la compra",
            500,
        )

    if not compra:
        abort(404)

    if request.method == "GET":
        return render_template(
            "editar_compra.html",
            compra=compra,
        )

    producto = obtener_campo(
        "producto",
        "product",
        "nombre_producto",
    )

    proveedor = obtener_campo(
        "proveedor",
        "provider",
    )

    cliente = obtener_campo(
        "cliente",
        "client",
        "nombre_cliente",
    )

    monto_texto = obtener_campo(
        "monto",
        "amount",
    )

    fecha_texto = obtener_campo(
        "fecha",
        "date",
    )

    if not producto:
        app.logger.warning(
            "Edición sin producto. Campos: %s",
            list(request.form.keys()),
        )

        return (
            "No se recibió el producto. "
            "Cierra y vuelve a abrir la aplicación.",
            400,
        )

    if not proveedor:
        return (
            "Debes escribir el proveedor",
            400,
        )

    try:
        monto = convertir_monto(
            monto_texto
        )

        fecha_nueva = convertir_fecha(
            fecha_texto
        )

    except ValueError as error:
        return str(error), 400

    archivo_nuevo = (
        request.files.get("foto")
        or request.files.get("evidencia")
    )

    evidencia_nueva = (
        compra["evidencia"]
    )

    evidencia_subida = False

    if (
        archivo_nuevo is not None
        and archivo_nuevo.filename
    ):
        try:
            evidencia_nueva = guardar_evidencia(
                archivo_nuevo
            )

            evidencia_subida = True

        except ValueError as error:
            return str(error), 400

        except Exception:
            app.logger.exception(
                "Error guardando evidencia nueva"
            )

            return (
                "No se pudo guardar la evidencia",
                500,
            )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE compras

                    SET
                        producto = %s,
                        proveedor = %s,
                        cliente = %s,
                        monto = %s,
                        fecha = %s,
                        evidencia = %s

                    WHERE id = %s
                      AND user_id = %s
                      AND eliminado = FALSE
                    """,
                    (
                        producto,
                        proveedor,
                        cliente or None,
                        monto,
                        fecha_nueva,
                        evidencia_nueva,
                        id,
                        session["user_id"],
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error actualizando compra"
        )

        if evidencia_subida:
            borrar_evidencia(
                evidencia_nueva
            )

        return (
            "No se pudo actualizar la compra",
            500,
        )

    if (
        evidencia_subida
        and compra["evidencia"]
        != evidencia_nueva
    ):
        borrar_evidencia(
            compra["evidencia"]
        )

    return redirect(
        url_for(
            "historial_dia",
            fecha=fecha_nueva.isoformat(),
        )
    )


# ==================================================
# PAPELERA
# ==================================================

@app.route(
    "/eliminar/<int:id>",
    methods=["POST"],
)
@login_requerido
def eliminar_compra(id):
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE compras
                    SET eliminado = TRUE

                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        id,
                        session["user_id"],
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error enviando compra a papelera"
        )

        return (
            "No se pudo eliminar la compra",
            500,
        )

    return redirect(
        url_for("historial")
    )


@app.route("/papelera")
@login_requerido
def papelera():
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        producto,
                        proveedor,
                        cliente,
                        monto,
                        fecha,
                        evidencia

                    FROM compras

                    WHERE user_id = %s
                      AND eliminado = TRUE

                    ORDER BY fecha DESC, id DESC
                    """,
                    (
                        session["user_id"],
                    ),
                )

                lista_compras = (
                    cursor.fetchall()
                )

    except Exception:
        app.logger.exception(
            "Error cargando papelera"
        )

        return (
            "No se pudo cargar la papelera",
            500,
        )

    return render_template(
        "papelera.html",
        compras=lista_compras,
    )


@app.route(
    "/restaurar/<int:id>",
    methods=["POST"],
)
@login_requerido
def restaurar_compra(id):
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE compras
                    SET eliminado = FALSE

                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        id,
                        session["user_id"],
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error restaurando compra"
        )

        return (
            "No se pudo restaurar la compra",
            500,
        )

    return redirect(
        url_for("papelera")
    )


@app.route(
    "/eliminar_definitivamente/<int:id>",
    methods=["POST"],
)
@login_requerido
def eliminar_definitivamente(id):
    evidencia = None

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT evidencia
                    FROM compras

                    WHERE id = %s
                      AND user_id = %s
                      AND eliminado = TRUE

                    LIMIT 1
                    """,
                    (
                        id,
                        session["user_id"],
                    ),
                )

                compra = cursor.fetchone()

                if compra:
                    evidencia = (
                        compra["evidencia"]
                    )

                    cursor.execute(
                        """
                        DELETE FROM compras

                        WHERE id = %s
                          AND user_id = %s
                          AND eliminado = TRUE
                        """,
                        (
                            id,
                            session["user_id"],
                        ),
                    )

    except Exception:
        app.logger.exception(
            "Error eliminando compra definitivamente"
        )

        return (
            "No se pudo eliminar la compra",
            500,
        )

    borrar_evidencia(
        evidencia
    )

    return redirect(
        url_for("papelera")
    )


# ==================================================
# REGISTRO
# ==================================================

@app.route("/registro")
def registro():
    return render_template(
        "registro.html"
    )


@app.route(
    "/crear_cuenta",
    methods=["POST"],
)
def crear_cuenta():
    usuario = request.form.get(
        "usuario",
        "",
    ).strip()

    email = request.form.get(
        "email",
        "",
    ).strip().lower()

    password_raw = request.form.get(
        "password",
        "",
    )

    if (
        not usuario
        or not email
        or not password_raw
    ):
        return "Faltan datos", 400

    if "@" not in email:
        return (
            "El correo no es válido",
            400,
        )

    if len(usuario) < 3:
        return (
            "El usuario debe tener al menos "
            "3 caracteres",
            400,
        )

    if len(password_raw) < 8:
        return (
            "La contraseña debe tener al menos "
            "8 caracteres",
            400,
        )

    password_hash = generate_password_hash(
        password_raw
    )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM usuarios

                    WHERE LOWER(email) = %s
                       OR LOWER(usuario) = %s

                    LIMIT 1
                    """,
                    (
                        email,
                        usuario.lower(),
                    ),
                )

                existe = cursor.fetchone()

                if existe:
                    return (
                        "El correo o usuario ya existe",
                        409,
                    )

                cursor.execute(
                    """
                    INSERT INTO usuarios (
                        usuario,
                        email,
                        password
                    )
                    VALUES (
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        usuario,
                        email,
                        password_hash,
                    ),
                )

    except UniqueViolation:
        return (
            "El correo o usuario ya existe",
            409,
        )

    except Exception:
        app.logger.exception(
            "Error creando cuenta"
        )

        return (
            "No se pudo crear la cuenta",
            500,
        )

    return redirect(
        url_for("login")
    )


# ==================================================
# RECUPERACIÓN DE CONTRASEÑA
# ==================================================

@app.route(
    "/recuperar",
    methods=["GET", "POST"],
)
def recuperar():
    if request.method == "GET":
        return render_template(
            "recuperar.html"
        )

    email = request.form.get(
        "email",
        "",
    ).strip().lower()

    if not email:
        return (
            "Debes escribir un correo",
            400,
        )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM usuarios

                    WHERE LOWER(email) = %s

                    LIMIT 1
                    """,
                    (email,),
                )

                usuario = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error buscando correo"
        )

        return (
            "No se pudo consultar el correo",
            500,
        )

    if usuario:
        if (
            not app.config["MAIL_USERNAME"]
            or not app.config["MAIL_PASSWORD"]
        ):
            return (
                "El servicio de correo "
                "no está configurado",
                503,
            )

        token = serializer.dumps(
            email,
            salt="recuperar-password",
        )

        base_url = (
            os.environ.get(
                "APP_BASE_URL"
            )
            or os.environ.get(
                "RENDER_EXTERNAL_URL"
            )
            or request.url_root.rstrip("/")
        ).rstrip("/")

        enlace = (
            f"{base_url}"
            f"/reset_password/{token}"
        )

        mensaje = Message(
            "Recuperación de contraseña",
            sender=app.config[
                "MAIL_USERNAME"
            ],
            recipients=[email],
        )

        mensaje.body = (
            "Utiliza el siguiente enlace para "
            "cambiar tu contraseña:\n\n"
            f"{enlace}\n\n"
            "El enlace vence en una hora."
        )

        try:
            mail.send(
                mensaje
            )

        except Exception:
            app.logger.exception(
                "Error enviando correo"
            )

            return (
                "No se pudo enviar el correo",
                500,
            )

    return (
        "Si el correo está registrado, "
        "recibirás un enlace de recuperación."
    )


@app.route(
    "/reset_password/<token>",
    methods=["GET", "POST"],
)
def reset_password(token):
    try:
        email = serializer.loads(
            token,
            salt="recuperar-password",
            max_age=3600,
        )

    except SignatureExpired:
        return (
            "El enlace ha expirado",
            400,
        )

    except BadSignature:
        return (
            "El enlace no es válido",
            400,
        )

    if request.method == "GET":
        return render_template(
            "reset_password.html",
            token=token,
        )

    password_raw = (
        request.form.get("password")
        or request.form.get(
            "nueva_password"
        )
        or request.form.get(
            "new_password"
        )
        or ""
    )

    confirmar = (
        request.form.get(
            "confirmar_password"
        )
        or request.form.get(
            "confirm_password"
        )
        or ""
    )

    if len(password_raw) < 8:
        return (
            "La contraseña debe tener al menos "
            "8 caracteres",
            400,
        )

    if (
        confirmar
        and password_raw != confirmar
    ):
        return (
            "Las contraseñas no coinciden",
            400,
        )

    password_hash = generate_password_hash(
        password_raw
    )

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE usuarios
                    SET password = %s

                    WHERE LOWER(email) = %s
                    """,
                    (
                        password_hash,
                        email.lower(),
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error cambiando contraseña"
        )

        return (
            "No se pudo cambiar la contraseña",
            500,
        )

    session.clear()

    return redirect(
        url_for("login")
    )


# ==================================================
# ERRORES
# ==================================================

@app.errorhandler(413)
def archivo_grande(_error):
    return (
        "El archivo supera el límite de 10 MB",
        413,
    )


@app.errorhandler(404)
def no_encontrado(_error):
    return (
        "La página o el archivo no existe",
        404,
    )


# ==================================================
# EJECUTAR
# ==================================================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "10000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
