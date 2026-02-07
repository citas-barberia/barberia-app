from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from datetime import date

app = Flask(__name__)
app.secret_key = "secret_key"  # Necesario para mensajes flash

# ===== Servicios con precios =====
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000
}

# ===== Función para leer citas desde citas.txt =====
def leer_citas():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if linea.strip() == "":
                    continue
                c = linea.strip().split("|")
                citas.append({
                    "cliente": c[0],
                    "barbero": c[1],
                    "servicio": c[2],
                    "precio": c[3],
                    "fecha": c[4],
                    "hora": c[5]
                })
    except FileNotFoundError:
        pass
    return citas

# ===== Función para guardar una cita =====
def guardar_cita(cliente, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{cliente}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")

# ===== Función para cancelar cita =====
def cancelar_cita(cliente, barbero, fecha, hora):
    citas = leer_citas()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            if c["cliente"] == cliente and c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora:
                f.write(f"{c['cliente']}|{c['barbero']}|CITA CANCELADA|{c['precio']}|{c['fecha']}|{c['hora']}\n")
            else:
                f.write(f"{c['cliente']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")

# ===== Ruta del cliente =====
@app.route("/", methods=["GET", "POST"])
def index():
    citas = leer_citas()

    if request.method == "POST":
        cliente = request.form["cliente"]
        barbero = request.form["barbero"]
        servicio = request.form["servicio"]
        precio = str(servicios.get(servicio, 0))
        fecha = request.form["fecha"]
        hora = request.form["hora"]

        # Verificar si la hora ya está ocupada para el mismo barbero y mismo día
        conflict = any(
            c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora and c["servicio"] != "CITA CANCELADA"
            for c in citas
        )

        if conflict:
            flash("La hora seleccionada ya está ocupada. Por favor elige otra.")
        else:
            guardar_cita(cliente, barbero, servicio, precio, fecha, hora)
            flash("Cita agendada exitosamente")

        return redirect(url_for("index"))

    return render_template("index.html", servicios=servicios, citas=citas)

# ===== Ruta de cancelar cita =====
@app.route("/cancelar", methods=["POST"])
def cancelar():
    cliente = request.form["cliente"]
    barbero = request.form["barbero"]
    fecha = request.form["fecha"]
    hora = request.form["hora"]

    cancelar_cita(cliente, barbero, fecha, hora)
    flash("Cita cancelada")
    return redirect(url_for("index"))

# ===== Ruta del barbero =====
@app.route("/barbero")
def barbero():
    citas = leer_citas()
    fecha_actual = date.today().strftime("%Y-%m-%d")
    return render_template("barbero.html", citas=citas, fecha_actual=fecha_actual)

# ===== Ruta JSON para actualizar las citas del barbero =====
@app.route("/citas_json")
def citas_json():
    citas = leer_citas()
    return jsonify({"citas": citas})

# ===== Ruta para horas disponibles =====
@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero = request.args.get("barbero")
    horas = ["09:00am","10:00am","11:00am","12:00md","1:00pm","2:00pm","3:00pm","4:00pm","5:00pm"]

    ocupadas = []
    citas = leer_citas()
    for c in citas:
        if c["barbero"] == barbero and c["fecha"] == fecha and c["servicio"] != "CITA CANCELADA":
            ocupadas.append(c["hora"])

    disponibles = [h for h in horas if h not in ocupadas]
    return jsonify(disponibles)

# ===== Arrancar servidor =====
if __name__ == "__main__":
    app.run(debug=True)
