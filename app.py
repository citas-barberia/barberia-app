from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import uuid
from datetime import date

app = Flask(__name__)
app.secret_key = "super_secret_key"

# ===== Servicios =====
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000
}

# ===== Leer citas =====
def leer_citas():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                partes = linea.strip().split("|")
                if len(partes) == 9:
                    citas.append({
                        "id": partes[0],
                        "cliente_id": partes[1],
                        "cliente": partes[2],
                        "barbero": partes[3],
                        "servicio": partes[4],
                        "precio": partes[5],
                        "fecha": partes[6],
                        "hora": partes[7],
                        "estado": partes[8]
                    })
    except FileNotFoundError:
        pass
    return citas


# ===== Guardar cita =====
def guardar_cita(c):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(
            f"{c['id']}|{c['cliente_id']}|{c['cliente']}|{c['barbero']}|"
            f"{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}|ACTIVA\n"
        )


# ===== Cancelar cita =====
def cancelar_cita(id_cita):
    citas = leer_citas()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            estado = "CANCELADA" if c["id"] == id_cita else c["estado"]
            f.write(
                f"{c['id']}|{c['cliente_id']}|{c['cliente']}|{c['barbero']}|"
                f"{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}|{estado}\n"
            )


# ===== Cliente =====
@app.route("/", methods=["GET", "POST"])
def index():
    if "cliente_id" not in session:
        session["cliente_id"] = str(uuid.uuid4())

    cliente_id = session["cliente_id"]

    if request.method == "POST":
        citas = leer_citas()

        fecha = request.form["fecha"]
        hora = request.form["hora"]
        barbero = request.form["barbero"]

        # 🔒 BLOQUEO REAL DE HORA
        for c in citas:
            if c["fecha"] == fecha and c["hora"] == hora and c["barbero"] == barbero:
                flash("Esa hora ya está ocupada")
                return redirect(url_for("index"))

        cita = {
            "id": str(uuid.uuid4()),
            "cliente_id": cliente_id,
            "cliente": request.form["cliente"],
            "barbero": barbero,
            "servicio": request.form["servicio"],
            "precio": servicios[request.form["servicio"]],
            "fecha": fecha,
            "hora": hora
        }

        guardar_cita(cita)
        return redirect(url_for("index"))

    # 👇 SOLO SUS CITAS
    citas_cliente = [
    c for c in leer_citas()
    if c["cliente_id"] == cliente_id and c["estado"] == "ACTIVA"
]


    return render_template("index.html", servicios=servicios, citas=citas_cliente)

# ===== Cancelar =====
@app.route("/cancelar", methods=["POST"])
def cancelar():
    cancelar_cita(request.form["id"])
    flash("Cita cancelada")
    return redirect(url_for("index"))

# ===== Horas disponibles =====
@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero = request.args.get("barbero")

    horas = [
        "09:00am","10:00am","11:00am",
        "12:00md","1:00pm","2:00pm",
        "3:00pm","4:00pm","5:00pm"
    ]

    ocupadas = [
    c["hora"] for c in leer_citas()
    if c["fecha"] == fecha
    and c["barbero"] == barbero
    and c["estado"] == "ACTIVA"
]


    return jsonify([h for h in horas if h not in ocupadas])

# ===== Barbero =====
@app.route("/barbero")
def barbero():
    return render_template(
        "barbero.html",
        citas=leer_citas(),
        fecha_actual=date.today().strftime("%Y-%m-%d")
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

