import os
import uuid
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, send_file, session
from itsdangerous import URLSafeTimedSerializer
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message

# =========================
# APP
# =========================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave_super_segura_123'
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
app.secret_key = "sistema_compras_2026"
# =========================
# GMAIL
# =========================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True

# TU CORREO GMAIL
app.config['MAIL_USERNAME'] = '202260821@ucc.mx'

# CONTRASEÑA DE APLICACIÓN
app.config['MAIL_PASSWORD'] = 'fpuv eroo zbdc reqq'

mail = Mail(app)

serializer = URLSafeTimedSerializer(app.secret_key)

# =========================
# MYSQL
# =========================
import os

app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST')
app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.environ.get('MYSQL_DB')

mysql = MySQL(app)
# =========================
# UPLOADS
# =========================
UPLOAD_FOLDER = 'uploads'

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# =========================
# LIMPIEZA PAPELERA (30 DÍAS)
# =========================
def limpiar_papelera():
    cursor = mysql.connection.cursor()
    cursor.execute("""
        DELETE FROM compras
        WHERE eliminado = 1
        AND fecha < DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """)
    mysql.connection.commit()


# =========================
# LOGIN
# =========================
@app.route('/')
def login():
    return render_template('login.html')


@app.route('/validar', methods=['POST'])
def validar():

    usuario = request.form['usuario']
    password = request.form['password']

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE usuario=%s", (usuario,))
    user = cursor.fetchone()

    if user and check_password_hash(user[2], password):
        session['user_id'] = user[0]
        session['usuario'] = user[1]
        return redirect('/compras')

    return "Login incorrecto"


# =========================
# SALIR (CORREGIDO)
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

    ruta = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
    file.save(ruta)

    cursor = mysql.connection.cursor()
    cursor.execute("""
        INSERT INTO compras
        (producto, proveedor, monto, fecha, evidencia, user_id, eliminado)
        VALUES (%s,%s,%s,%s,%s,%s,0)
    """, (producto, proveedor, monto, fecha, nombre_unico, session['user_id']))

    mysql.connection.commit()

    return redirect('/historial')


# =========================
# HISTORIAL
# =========================
@app.route('/historial')
def historial():

    if 'user_id' not in session:
        return redirect('/')

    cursor = mysql.connection.cursor()

    cursor.execute("""
        SELECT * FROM compras
        WHERE user_id=%s AND eliminado=0
        ORDER BY id DESC
    """, (session['user_id'],))

    compras = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*), IFNULL(SUM(monto),0)
        FROM compras
        WHERE user_id=%s AND eliminado=0
    """, (session['user_id'],))

    total_compras, total_gasto = cursor.fetchone()

    cursor.execute("""
        SELECT fecha, COUNT(*), SUM(monto)
        FROM compras
        WHERE user_id=%s AND eliminado=0
        GROUP BY fecha
        ORDER BY fecha DESC
    """, (session['user_id'],))

    por_dia = cursor.fetchall()

    return render_template(
        'historial.html',
        compras=compras,
        total_compras=total_compras,
        total_gasto=total_gasto,
        por_dia=por_dia
    )


# =========================
# ELIMINAR (PAPELERA)
# =========================
@app.route('/eliminar/<int:id>')
def eliminar(id):

    if 'user_id' not in session:
        return redirect('/')

    cursor = mysql.connection.cursor()
    cursor.execute("""
        UPDATE compras
        SET eliminado=1
        WHERE id=%s AND user_id=%s
    """, (id, session['user_id']))

    mysql.connection.commit()

    return redirect('/historial')


# =========================
# PAPELERA
# =========================
@app.route('/papelera')
def papelera():

    if 'user_id' not in session:
        return redirect('/')

    limpiar_papelera()

    cursor = mysql.connection.cursor()

    cursor.execute("""
        SELECT id, producto, proveedor, monto, fecha, evidencia
        FROM compras
        WHERE user_id=%s AND eliminado=1
        ORDER BY id DESC
    """, (session['user_id'],))

    compras = cursor.fetchall()

    return render_template('papelera.html', compras=compras)


# =========================
# RESTAURAR
# =========================
@app.route('/restaurar/<int:id>')
def restaurar(id):

    if 'user_id' not in session:
        return redirect('/')

    cursor = mysql.connection.cursor()
    cursor.execute("""
        UPDATE compras
        SET eliminado=0
        WHERE id=%s AND user_id=%s
    """, (id, session['user_id']))

    mysql.connection.commit()

    return redirect('/papelera')


# =========================
# VACÍAR PAPELERA
# =========================
@app.route('/vaciar_papelera')
def vaciar_papelera():

    if 'user_id' not in session:
        return redirect('/')

    cursor = mysql.connection.cursor()
    cursor.execute("""
        DELETE FROM compras
        WHERE user_id=%s AND eliminado=1
    """, (session['user_id'],))

    mysql.connection.commit()

    return redirect('/papelera')


# =========================
# EDITAR
# =========================
@app.route('/editar/<int:id>')
def editar(id):

    if 'user_id' not in session:
        return redirect('/')

    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT * FROM compras
        WHERE id=%s AND user_id=%s
    """, (id, session['user_id']))

    compra = cursor.fetchone()

    return render_template('editar.html', compra=compra)


# =========================
# ACTUALIZAR
# =========================
@app.route('/actualizar/<int:id>', methods=['POST'])
def actualizar(id):

    if 'user_id' not in session:
        return redirect('/')

    producto = request.form['producto']
    proveedor = request.form['proveedor']
    monto = request.form['monto']

    cursor = mysql.connection.cursor()

    if 'foto' in request.files and request.files['foto'].filename != '':

        file = request.files['foto']
        nombre_unico = str(uuid.uuid4()) + "_" + secure_filename(file.filename)

        ruta = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
        file.save(ruta)

        cursor.execute("""
            SELECT evidencia FROM compras
            WHERE id=%s AND user_id=%s
        """, (id, session['user_id']))

        old = cursor.fetchone()

        if old:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old[0])
            if os.path.exists(old_path):
                os.remove(old_path)

        cursor.execute("""
            UPDATE compras
            SET producto=%s, proveedor=%s, monto=%s, evidencia=%s
            WHERE id=%s AND user_id=%s
        """, (producto, proveedor, monto, nombre_unico, id, session['user_id']))

    else:

        cursor.execute("""
            UPDATE compras
            SET producto=%s, proveedor=%s, monto=%s
            WHERE id=%s AND user_id=%s
        """, (producto, proveedor, monto, id, session['user_id']))

    mysql.connection.commit()

    return redirect('/historial')


# =========================
# IMÁGENES
# =========================
@app.route('/uploads/<filename>')
def uploads(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

# =========================
# FORMULARIO REGISTRO
# =========================
@app.route('/registro')
def registro():
    return render_template('registro.html')
    
# =========================
# REGISTRO
# =========================
@app.route('/crear_cuenta', methods=['POST'])
def crear_cuenta():

    usuario = request.form.get('usuario')
    email = request.form.get('email')
    password_raw = request.form.get('password')

    if not usuario or not email or not password_raw:
        return "Faltan datos del formulario"

    password = generate_password_hash(password_raw)

    cursor = mysql.connection.cursor()

    cursor.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
    existe = cursor.fetchone()

    if existe:
        return "El correo ya existe"

    cursor.execute("""
        INSERT INTO usuarios(usuario, email, password)
        VALUES (%s, %s, %s)
    """, (usuario, email, password))

    mysql.connection.commit()

    return redirect('/')

# =========================
# RECUPERAR PASSWORD
# =========================
@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():

    if request.method == 'POST':

        email = request.form['email']

        cursor = mysql.connection.cursor()

        cursor.execute(
            "SELECT * FROM usuarios WHERE usuario=%s",
            (email,)
        )

        user = cursor.fetchone()

        if user:

            token = serializer.dumps(
                email,
                salt='recuperar-password'
            )

            link = f"http://192.168.200.191:5000/reset_password/{token}"

            msg = Message(
                'Recuperación de contraseña',
                sender=app.config['MAIL_USERNAME'],
                recipients=[email]
            )

            msg.body = f'''Hola.

Haz clic en el siguiente enlace para recuperar tu contraseña:

{link}
'''

            try:

                mail.send(msg)

                return "Correo enviado correctamente"

            except Exception as e:

                return str(e)

        return "El correo no existe"

    return render_template('recuperar.html')


# =========================
# RESET PASSWORD
# =========================
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):

    try:

        email = serializer.loads(
            token,
            salt='recuperar-password',
            max_age=3600
        )

    except:
        return "El enlace expiró"

    if request.method == 'POST':

        nueva = generate_password_hash(
            request.form['password']
        )

        cursor = mysql.connection.cursor()

        cursor.execute("""
            UPDATE usuarios
            SET password=%s
            WHERE usuario=%s
        """, (nueva, email))

        mysql.connection.commit()

        return redirect('/')

    return render_template(
        'reset_password.html'
    )

# =========================
# RUN
# =========================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

