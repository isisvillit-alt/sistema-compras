import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, send_file, session, send_from_directory
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
import pymysql

# =========================
# APP
# =========================
app = Flask(__name__)
app.secret_key = "sistema_compras_2026"

serializer = URLSafeTimedSerializer(app.secret_key)

# =========================
# MAIL
# =========================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = '202260821@ucc.mx'
app.config['MAIL_PASSWORD'] = 'fpuv eroo zbdc reqq'

mail = Mail(app)

# =========================
# MYSQL (PRODUCCIÓN ROBUSTA)
# =========================
def get_db():
    return pymysql.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=int(os.getenv("MYSQLPORT")),
        cursorclass=pymysql.cursors.DictCursor
    )

# =========================
# UPLOADS
# =========================
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# =========================
# LOGIN
# =========================
@app.route('/')
def login():
    return render_template('login.html')


@app.route('/validar', methods=['POST'])
def validar():
    usuario = request.form['email']
    password = request.form['password']

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
    user = cursor.fetchone()

    db.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['email'] = user['email']
        return redirect('/compras')

    return "Login incorrecto"


# =========================
# LOGOUT
# =========================
@app.route('/salir')
def salir():
    session.clear()
    return redirect('/')


# =========================
# COMPRAS
# =========================
@app.route('/compras')
def compras():
    if 'user_id' not in session:
        return redirect('/')
    return render_template('compras.html')


# =========================
# GUARDAR COMPRA
# =========================
@app.route('/guardar', methods=['POST'])
def guardar():
    if 'user_id' not in session:
        return redirect('/')

    producto = request.form['producto']
    proveedor = request.form['proveedor']
    monto = request.form['monto']
    fecha = datetime.now().date()

    file = request.files['foto']
    nombre_unico = str(uuid.uuid4()) + "_" + secure_filename(file.filename)

    file.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico))

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO compras (producto, proveedor, monto, fecha, evidencia, user_id, eliminado)
        VALUES (%s,%s,%s,%s,%s,%s,0)
    """, (producto, proveedor, monto, fecha, nombre_unico, session['user_id']))

    db.commit()
    db.close()

    return redirect('/historial')


# =========================
# HISTORIAL
# =========================
@app.route('/historial')
def historial():

    if 'user_id' not in session:
        return redirect('/')

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT *
        FROM compras
        WHERE user_id=%s
        AND eliminado=0
        ORDER BY fecha DESC
    """, (session['user_id'],))

    compras = cursor.fetchall()

    cursor.execute("""
        SELECT
            fecha,
            COUNT(*) as cantidad,
            SUM(monto) as total
        FROM compras
        WHERE user_id=%s
        AND eliminado=0
        GROUP BY fecha
        ORDER BY fecha DESC
    """, (session['user_id'],))

    por_dia = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) as total,
            IFNULL(SUM(monto),0) as gasto
        FROM compras
        WHERE user_id=%s
        AND eliminado=0
    """, (session['user_id'],))

    resumen = cursor.fetchone()

    db.close()

    return render_template(
        'historial.html',
        compras=compras,
        por_dia=por_dia,
        total_compras=resumen['total'],
        total_gasto=resumen['gasto']
    )


# =========================
# ELIMINAR (PAPELERA)
# =========================
@app.route('/eliminar/<int:id>')
def eliminar(id):
    if 'user_id' not in session:
        return redirect('/')

    db = get_db()
    cursor = db.cursor()

    cursor.execute("UPDATE compras SET eliminado=1 WHERE id=%s AND user_id=%s",
                   (id, session['user_id']))

    db.commit()
    db.close()

    return redirect('/historial')


# =========================
# PAPELERA
# =========================
@app.route('/papelera')
def papelera():
    if 'user_id' not in session:
        return redirect('/')

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM compras WHERE user_id=%s AND eliminado=1",
                   (session['user_id'],))
    compras = cursor.fetchall()

    db.close()

    return render_template('papelera.html', compras=compras)


# =========================
# RESTAURAR
# =========================
@app.route('/restaurar/<int:id>')
def restaurar(id):
    if 'user_id' not in session:
        return redirect('/')

    db = get_db()
    cursor = db.cursor()

    cursor.execute("UPDATE compras SET eliminado=0 WHERE id=%s AND user_id=%s",
                   (id, session['user_id']))

    db.commit()
    db.close()

    return redirect('/papelera')
    # =========================
# FORMULARIO REGISTRO
# =========================
@app.route('/registro')
def registro():
    return render_template('registro.html')


# =========================
# CREAR CUENTA
# =========================
@app.route('/crear_cuenta', methods=['POST'])
def crear_cuenta():

    try:

        usuario = request.form.get('usuario')
        email = request.form.get('email')
        password_raw = request.form.get('password')

        if not usuario or not email or not password_raw:
            return "Faltan datos"

        password = generate_password_hash(password_raw)

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "SELECT * FROM usuarios WHERE email=%s",
            (email,)
        )

        existe = cursor.fetchone()

        if existe:
            db.close()
            return "El correo ya existe"

        cursor.execute("""
            INSERT INTO usuarios(usuario, email, password)
            VALUES (%s, %s, %s)
        """, (usuario, email, password))

        db.commit()
        db.close()

        return redirect('/')

    except Exception as e:
        return f"ERROR REAL: {str(e)}"

# =========================
# RESET PASSWORD (FIX)
# =========================
@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        email = request.form['email']

        db = get_db()
        cursor = db.cursor()

        cursor.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
        user = cursor.fetchone()

        db.close()

        if user:
            token = serializer.dumps(email, salt='recuperar-password')

            link = f"https://TU-DOMINIO.onrender.com/reset_password/{token}"

            msg = Message(
                'Recuperación de contraseña',
                sender=app.config['MAIL_USERNAME'],
                recipients=[email]
            )

            msg.body = f"Clic aquí: {link}"

            mail.send(msg)

            return "Correo enviado"

        return "No existe"

    return render_template('recuperar.html')
# =========================
# VER IMÁGENES SUBIDAS
# =========================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename
    )

# =========================
# RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
