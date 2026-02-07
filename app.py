from flask import Flask, render_template, request, redirect, url_for, flash
import uuid
from datetime import date
import requests
import os

app = Flask(__name__)
app.secret_key = "secret_key"

# ===== CONFIG =====
VERIFY_TOKEN = "barberia123"
NUMERO_BARBERO = "50672314147"
DOMINIO = "https://barberia-app-1.onrender.com"

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# ===== Servicios =====
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000
}

# ===== HORAS DISPONIBLES =====
HORAS = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00", "16:00", "17:00"]


# ===== Enviar mensaje al barbero =====
def enviar_whatsapp(mensaje):

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": NUMERO_BARBERO,
        "type": "text",
        "text": {"body": mensaje}
    }

    requests.post(url, headers=headers, json=data)


# ===== Responder cliente =====
def enviar_whatsapp_respuesta(numero, mensaje):

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensaje}
    }

    requests.post(url, headers=headers, json=data)


# ===== WEBHOOK =====
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":

        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token == VERIFY_TOKEN:
            return challenge
        return "Token incorrecto", 403


    if request.method == "POST":

        data = request.get_json()

        try:
            numero = data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]

            link = f"{DOMINIO}/?cliente_id={numero}"

            mensaje = f"""Hola 👋 Bienvenido a Barbería José 💈

Puede agendar su cita aquí:
{link}
"""

            enviar_whatsapp_respuesta(numero, mensaje)

        except Exception as e:
            print("Error webhook:", e)

        return "ok", 200


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


# ===== HORAS DISPONIBLES SEGUN FECHA Y BARBERO =====
def horas_disponibles(fecha, barbero):

    ocupadas = [
        c["hora"] for c in leer_citas()
        if c["fecha"] == fecha and c["barbero"] == barbero
    ]

    return [h for h in HORAS if h not in ocupadas]


# ===== Guardar =====
def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")


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

        guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

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

    # 👉 Mandamos horas al HTML
    return render_template(
        "index.html",
        servicios=servicios,
        citas=citas,
        horas=HORAS
    )


# ===== VER CITA =====
@app.route("/cita/<id_cita>")
def ver_cita(id_cita):

    cliente_id = request.args.get("cliente_id")

    citas = leer_citas()

    cita = next((c for c in citas if c["id"] == id_cita and c["cliente_id"] == cliente_id), None)

    if not cita:
        return "Cita no encontrada", 404

    return render_template("index.html", servicios=servicios, citas=[cita], horas=HORAS)


# ===== PANEL BARBERO =====
@app.route("/barbero")
def barbero():
    return render_template("barbero.html", citas=leer_citas(), fecha_actual=date.today())


if __name__ == "__main__":
    app.run(debug=True)








