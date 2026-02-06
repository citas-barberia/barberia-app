from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import uuid
from datetime import date
import requests

app = Flask(__name__)
app.secret_key = "secret_key"

NUMERO_BARBERO = "50672314147"

# ===== Servicios =====
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000
}

# ===== WhatsApp =====
def enviar_whatsapp(mensaje):
    url = "https://graph.facebook.com/v22.0/994974633695883/messages"

    headers = {
        "Authorization": "Bearer EAAMIUG0X8IgBQoayf9T96izlZCcWLnmDiaBIM3fr8r8RhOkjaTFKpLqHXiWAjb7CbalQC5GaP8BXtDc4YZCyace0nXUm9gMxLbtjYYOpChFcPbZAXzZBHFcmKNeQ7bsZBKYJphbOnBb8GtQFq21mgq1aDneFt9mUNoR27AKZCTH0yjc9wfYqwoebm2ps3zvSFBZAFQMCxsl5IIg8JE1OUZAJtGlXAnT6jUgtWha9XyZBF3oTTIhDbSCDL7CxjZBaYBPHsap07RGsG8IOJiI883En4v",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": NUMERO_BARBERO,
        "type": "text",
        "text": {"body": mensaje}
    }

    try:
        requests.post(url, headers=headers, json=data)
    except:
        print("Error enviando WhatsApp")


# ===== Leer citas =====
def leer_citas():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if linea.strip() == "":
                    continue

                partes = linea.strip().split("|")

                if len(partes) != 8:
                    continue

                id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora = partes

                citas.append({
                    "id": id_cita,
                    "cliente": cliente,
                    "cliente_id": cliente_id,
                    "barbero": barbero,
                    "servicio": servicio,
                    "precio": precio,
                    "fecha": fecha,
                    "hora": hora
                })
    except FileNotFoundError:
        pass

    return citas


# ===== Guardar =====
def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")


# ===== Cancelar =====
def cancelar_cita(id_cita):
    citas = leer_citas()

    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            if c["id"] == id_cita:
                c["servicio"] = "CITA CANCELADA"

            f.write(f"{c['id']}|{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")


# ===== INDEX =====
@app.route("/", methods=["GET", "POST"])
def index():

    cliente_id = request.args.get("cliente_id")

    if not cliente_id:
        cliente_id = str(uuid.uuid4())

    if request.method == "POST":

        cliente = request.form["cliente"]
        barbero = request.form["barbero"]
        servicio = request.form["servicio"]
        fecha = request.form["fecha"]
        hora = request.form["hora"]

        precio = str(servicios[servicio])
        id_cita = str(uuid.uuid4())

        citas = leer_citas()

        # Verificar choque de hora
        conflicto = any(
            c["barbero"] == barbero and
            c["fecha"] == fecha and
            c["hora"] == hora and
            c["servicio"] != "CITA CANCELADA"
            for c in citas
        )

        if conflicto:
            flash("La hora ya está ocupada")
            return redirect(url_for("index", cliente_id=cliente_id))

        guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

        # ===== MENSAJE WHATSAPP =====
        mensaje = f"""
💈 Nueva cita agendada

Cliente: {cliente}
Barbero: {barbero}
Servicio: {servicio}
Fecha: {fecha}
Hora: {hora}
Precio: ₡{precio}
"""

        enviar_whatsapp(mensaje)

        flash("Cita agendada exitosamente")

        return redirect(url_for("ver_cita", id_cita=id_cita, cliente_id=cliente_id))

    citas = [c for c in leer_citas() if c["cliente_id"] == cliente_id]

    return render_template("index.html", servicios=servicios, citas=citas)


# ===== VER CITA PRIVADA =====
@app.route("/cita/<id_cita>")
def ver_cita(id_cita):

    cliente_id = request.args.get("cliente_id")
    citas = leer_citas()

    cita = next((c for c in citas if c["id"] == id_cita and c["cliente_id"] == cliente_id), None)

    if not cita:
        return "Cita no encontrada", 404

    return render_template("index.html", servicios=servicios, citas=[cita])


# ===== CANCELAR =====
@app.route("/cancelar", methods=["POST"])
def cancelar():

    id_cita = request.form["id"]
    cliente_id = request.args.get("cliente_id")

    citas = leer_citas()
    cita = next((c for c in citas if c["id"] == id_cita and c["cliente_id"] == cliente_id), None)

    if cita:
        cancelar_cita(id_cita)
        flash("Cita cancelada")

    return redirect(url_for("index", cliente_id=cliente_id))


# ===== HORAS =====
@app.route("/horas")
def horas():

    fecha = request.args.get("fecha")
    barbero = request.args.get("barbero")

    horas = ["09:00am","10:00am","11:00am","12:00md","1:00pm","2:00pm","3:00pm","4:00pm","5:00pm"]

    ocupadas = [
        c["hora"] for c in leer_citas()
        if c["fecha"] == fecha and c["barbero"] == barbero and c["servicio"] != "CITA CANCELADA"
    ]

    return jsonify([h for h in horas if h not in ocupadas])


# ===== PANEL BARBERO =====
@app.route("/barbero")
def barbero():
    return render_template("barbero.html", citas=leer_citas(), fecha_actual=date.today())




