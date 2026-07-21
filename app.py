import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
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
    """
    Obtiene una variable de entorno obligatoria.
    """
    valor = os.environ.get(nombre)

    if not valor:
        raise RuntimeError(
            f"Falta la variable de entorno: {nombre}"
        )

    return valor


def usuario_autenticado():
    """
    Comprueba si existe una sesión iniciada.
    """
    return "user_id" in session


# ==================================================
# CONFIGURACIÓN DE FLASK
# ==================================================

app = Flask(__name__)

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


# ==================================================
# EVITAR CACHÉ EN PÁGINAS DINÁMICAS
# ==================================================

@app.after_request
def evitar_cache(response):
    """
    Evita que el navegador muestre versiones antiguas
    del historial después de guardar una compra.
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
# CONFIGURACIÓN DEL CORREO
# ==================================================

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True

app.config["MAIL_USERNAME"] = os.environ.get(
    "MAIL_USERNAME"
)

app.config["MAIL_PASSWORD"] = os.environ.get(
    "MAIL_PASSWORD"
)

mail = Mail(app)


# ==================================================
# POSTGRESQL / SUPABASE
# ==================================================

def get_db():
    """
    Crea una conexión con PostgreSQL de Supabase.
    """
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
# ARCHIVOS DE EVIDENCIA
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
    """
    Comprueba que el archivo tenga una extensión
    permitida.
    """
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


@app.route(
    "/uploads/<path:nombre_archivo>"
)
def mostrar_archivo(nombre_archivo):
    """
    Muestra una evidencia únicamente cuando pertenece
    al usuario que inició sesión.
    """
    if not usuario_autenticado():
        return redirect("/")

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

                evidencia = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error consultando evidencia"
        )

        return (
            "No se pudo consultar la evidencia",
            500,
        )

    if not evidencia:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        nombre_archivo,
    )


# ==================================================
# INICIO DE SESIÓN
# ==================================================

@app.route("/")
def login():
    if usuario_autenticado():
        return redirect("/compras")

    return render_template(
        "login.html"
    )


@app.route(
    "/validar",
    methods=["POST"],
)
def validar():
    """
    Permite iniciar sesión con correo electrónico
    o nombre de usuario.
    """
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

                user = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error consultando usuario"
        )

        return (
            "No se pudo conectar con la base de datos",
            500,
        )

    if (
        user
        and check_password_hash(
            user["password"],
            password,
        )
    ):
        session.clear()

        session["user_id"] = user["id"]
        session["usuario"] = user["usuario"]

        return redirect("/compras")

    return (
        "Correo o contraseña incorrectos",
        401,
    )


# ==================================================
# CERRAR SESIÓN
# ==================================================

@app.route("/salir")
def salir():
    session.clear()

    return redirect("/")


# ==================================================
# FORMULARIO DE NUEVA COMPRA
# ==================================================

@app.route("/compras")
def compras():
    if not usuario_autenticado():
        return redirect("/")

    return render_template(
        "compras.html"
    )


# ==================================================
# GUARDAR COMPRA
# ==================================================

@app.route(
    "/guardar",
    methods=["POST"],
)
def guardar():
    if not usuario_autenticado():
        return redirect("/")

    producto = request.form.get(
        "producto",
        "",
    ).strip()

    proveedor = request.form.get(
        "proveedor",
        "",
    ).strip()

    monto_texto = request.form.get(
        "monto",
        "",
    ).strip()

    fecha_texto = request.form.get(
        "fecha",
        "",
    ).strip()

    if (
        not producto
        or not proveedor
        or not monto_texto
    ):
        return (
            "Faltan datos de la compra",
            400,
        )

    # Convertir monto
    try:
        monto = Decimal(
            monto_texto.replace(
                ",",
                ".",
            )
        )

        if not monto.is_finite():
            raise InvalidOperation

        monto = monto.quantize(
            Decimal("0.01")
        )

    except InvalidOperation:
        return (
            "El monto no es válido",
            400,
        )

    if monto < 0:
        return (
            "El monto no puede ser negativo",
            400,
        )

    # Obtener fecha del formulario o usar hoy
    if fecha_texto:
        try:
            fecha = datetime.strptime(
                fecha_texto,
                "%Y-%m-%d",
            ).date()

        except ValueError:
            return (
                "La fecha no es válida",
                400,
            )

    else:
        fecha = datetime.now().date()

    archivo = request.files.get(
        "foto"
    )

    if (
        archivo is None
        or not archivo.filename
    ):
        return (
            "Debes seleccionar una evidencia",
            400,
        )

    if not archivo_permitido(
        archivo.filename
    ):
        return (
            "Solo se permiten archivos "
            "JPG, JPEG, PNG, WEBP o PDF",
            400,
        )

    nombre_seguro = secure_filename(
        archivo.filename
    )

    if not nombre_seguro:
        return (
            "El nombre del archivo no es válido",
            400,
        )

    nombre_unico = (
        f"{uuid.uuid4()}_"
        f"{nombre_seguro}"
    )

    ruta_archivo = os.path.join(
        app.config["UPLOAD_FOLDER"],
        nombre_unico,
    )

    try:
        archivo.save(
            ruta_archivo
        )

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
                        FALSE
                    )
                    """,
                    (
                        producto,
                        proveedor,
                        monto,
                        fecha,
                        nombre_unico,
                        session["user_id"],
                    ),
                )

    except Exception:
        app.logger.exception(
            "Error guardando compra"
        )

        if os.path.exists(
            ruta_archivo
        ):
            os.remove(
                ruta_archivo
            )

        return (
            "No se pudo guardar la compra",
            500,
        )

    return redirect(
        "/historial"
    )


# ==================================================
# HISTORIAL
# ==================================================

@app.route("/historial")
def historial():
    """
    Organiza las compras de la siguiente manera:

    Todas las compras
        Mes
            Día
                Compras
    """
    if not usuario_autenticado():
        return redirect("/")

    nombres_meses = {
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

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                # Obtener todas las compras activas
                cursor.execute(
                    """
                    SELECT
                        id,
                        producto,
                        proveedor,
                        monto,
                        fecha,
                        evidencia,
                        user_id,
                        eliminado
                    FROM compras
                    WHERE user_id = %s
                      AND eliminado = FALSE
                    ORDER BY fecha DESC, id DESC
                    """,
                    (
                        session["user_id"],
                    ),
                )

                lista_compras = (
                    cursor.fetchall()
                )

                # Obtener resumen general
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COALESCE(
                            SUM(monto),
                            0
                        ) AS gasto
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

    # ==================================================
    # AGRUPAR PRIMERO POR MES Y DESPUÉS POR DÍA
    # ==================================================

    grupos_meses = {}

    for compra in lista_compras:
        fecha = compra["fecha"]

        clave_mes = fecha.strftime(
            "%Y-%m"
        )

        clave_dia = fecha.isoformat()

        monto = (
            compra["monto"]
            if compra["monto"] is not None
            else Decimal("0.00")
        )

        # Crear carpeta del mes
        if clave_mes not in grupos_meses:
            grupos_meses[clave_mes] = {
                "clave": clave_mes,
                "nombre": (
                    f"{nombres_meses[fecha.month]} "
                    f"{fecha.year}"
                ),
                "cantidad": 0,
                "total": Decimal("0.00"),
                "dias": {},
            }

        mes = grupos_meses[
            clave_mes
        ]

        mes["cantidad"] += 1
        mes["total"] += monto

        # Crear carpeta del día
        if clave_dia not in mes["dias"]:
            mes["dias"][clave_dia] = {
                "clave": clave_dia,
                "fecha": fecha,
                "cantidad": 0,
                "total": Decimal("0.00"),
                "compras": [],
            }

        dia = mes["dias"][
            clave_dia
        ]

        dia["cantidad"] += 1
        dia["total"] += monto
        dia["compras"].append(
            compra
        )

    # Ordenar meses del más reciente al más antiguo
    meses = sorted(
        grupos_meses.values(),
        key=lambda elemento: elemento["clave"],
        reverse=True,
    )

    # Ordenar los días de cada mes
    for mes in meses:
        mes["dias"] = sorted(
            mes["dias"].values(),
            key=lambda elemento: elemento["clave"],
            reverse=True,
        )

    return render_template(
        "historial.html",
        compras=lista_compras,
        meses=meses,
        total_compras=resumen["total"],
        total_gasto=resumen["gasto"],
    )


# ==================================================
# ENVIAR COMPRA A PAPELERA
# ==================================================

@app.route(
    "/eliminar/<int:id>",
    methods=["GET", "POST"],
)
def eliminar(id):
    if not usuario_autenticado():
        return redirect("/")

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
        "/historial"
    )


# ==================================================
# PAPELERA
# ==================================================

@app.route("/papelera")
def papelera():
    if not usuario_autenticado():
        return redirect("/")

    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        producto,
                        proveedor,
                        monto,
                        fecha,
                        evidencia,
                        user_id,
                        eliminado
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


# ==================================================
# RESTAURAR COMPRA
# ==================================================

@app.route(
    "/restaurar/<int:id>",
    methods=["GET", "POST"],
)
def restaurar(id):
    if not usuario_autenticado():
        return redirect("/")

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
        "/papelera"
    )


# ==================================================
# ELIMINAR COMPRA DEFINITIVAMENTE
# ==================================================

@app.route(
    "/eliminar_definitivamente/<int:id>",
    methods=["GET", "POST"],
)
def eliminar_definitivamente(id):
    """
    Elimina definitivamente una compra que se encuentra
    en la papelera y también intenta eliminar su evidencia.
    """
    if not usuario_autenticado():
        return redirect("/")

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
                    evidencia = compra["evidencia"]

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

    if evidencia:
        ruta_archivo = os.path.join(
            app.config["UPLOAD_FOLDER"],
            evidencia,
        )

        if os.path.exists(
            ruta_archivo
        ):
            try:
                os.remove(
                    ruta_archivo
                )

            except OSError:
                app.logger.exception(
                    "No se pudo eliminar la evidencia"
                )

    return redirect(
        "/papelera"
    )


# ==================================================
# FORMULARIO DE REGISTRO
# ==================================================

@app.route("/registro")
def registro():
    return render_template(
        "registro.html"
    )


# ==================================================
# CREAR CUENTA
# ==================================================

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
        return (
            "Faltan datos",
            400,
        )

    if "@" not in email:
        return (
            "El correo electrónico no es válido",
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

    password_hash = (
        generate_password_hash(
            password_raw
        )
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

    return redirect("/")


# ==================================================
# RECUPERAR CONTRASEÑA
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

                user = cursor.fetchone()

    except Exception:
        app.logger.exception(
            "Error buscando correo"
        )

        return (
            "No se pudo consultar el correo",
            500,
        )

    if user:
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

        link = (
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
            f"{link}\n\n"
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


# ==================================================
# RESTABLECER CONTRASEÑA
# ==================================================

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

    if not password_raw:
        return (
            "Debes escribir una contraseña",
            400,
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

    password_hash = (
        generate_password_hash(
            password_raw
        )
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
            "Error restableciendo contraseña"
        )

        return (
            "No se pudo cambiar la contraseña",
            500,
        )

    session.clear()

    return redirect("/")


# ==================================================
# ERRORES
# ==================================================

@app.errorhandler(413)
def archivo_demasiado_grande(_error):
    return (
        "El archivo supera el límite de 10 MB",
        413,
    )


@app.errorhandler(404)
def pagina_no_encontrada(_error):
    return (
        "La página o el archivo no existe",
        404,
    )


# ==================================================
# EJECUTAR APLICACIÓN
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