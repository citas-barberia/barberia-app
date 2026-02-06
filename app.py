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
        "Authorization": "Bearer TU_TOKEN_AQUI",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": NUMERO_BARBERO,
        "type": "text",
        "text": {"body": mensaje}
    }
    requests.post(url, headers=headers, json=data)

# ===== Leer citas =====
def leer_citas():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                partes = linea.strip().split("|")
                if len(partes) != 7:
                    continue
                id_cita, cliente, barbero, servicio, precio, fecha, hora = partes
                citas.append({
                    "id": id_cita,
                    "cliente": cliente,
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
def guardar_cita(c):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{c['id']}|{c['cliente']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")

# ===== Cancelar =====
def cancelar_cita(id_cita):
    citas = leer_citas()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            if c["id"] == id_cita:
                c["servicio"] = "CITA CANCELADA"
            f.write(f"{c['id']}|{c['cliente']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")

# ===== INDEX (AGENDAR) =====
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        cliente = request.form["cliente"]
        barbero = request.form["barbero"]
        servicio = request.form["servicio"]
        fecha = request.form["fecha"]
        hora = request.form["hora"]
        precio = str(servicios[servicio])

        citas = leer_citas()
        if any(c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora and c["servicio"] != "CITA CANCELADA" for c in citas):
            flash("Hora no disponible")
            return redirect(url_for("index"))

        id_cita = str(uuid.uuid4())

        cita = {
            "id": id_cita,
            "cliente": cliente,
            "barbero": barbero,
            "servicio": servicio,
            "precio": precio,
            "fecha": fecha,
            "hora": hora
        }

        guardar_cita(cita)

        enviar_whatsapp(
            f"📅 NUEVA CITA\n\nCliente: {cliente}\nBarbero: {barbero}\nFecha: {fecha}\nHora: {hora}"
        )

        return redirect(url_for("ver_cita", id_cita=id_cita))

    return render_template("index.html", servicios=servicios, citas=[])

# ===== CITA PRIVADA =====
@app.route("/cita/<id_cita>")
def ver_cita(id_cita):
    citas = leer_citas()
    cita = next((c for c in citas if c["id"] == id_cita), None)
    if not cita:
        return "Cita no encontrada", 404
    return render_template("index.html", servicios=servicios, citas=[cita])

# ===== CANCELAR =====
@app.route("/cancelar", methods=["POST"])
def cancelar():
    id_cita = request.form["id"]
    cancelar_cita(id_cita)
    flash("Cita cancelada")
    return redirect(url_for("index"))

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

# ===== BARBERO =====
@app.route("/barbero")
def barbero():
    return render_template("barbero.html", citas=leer_citas(), fecha_actual=date.today())


