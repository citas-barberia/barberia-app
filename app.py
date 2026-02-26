from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import date, timedelta, datetime
import os
import uuid
import requests
import time  # anti-duplicados webhook

app = Flask(__name__)
app.secret_key = "secret_key"

# =========================
# CONFIG WHATSAPP (Meta)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "barberia123")
NUMERO_BARBERO = os.getenv("NUMERO_BARBERO", "50672314147")
DOMINIO = os.getenv("DOMINIO", "https://barberia-app-1.onrender.com")

# ✅ Nombre del barbero
NOMBRE_BARBERO = os.getenv("NOMBRE_BARBERO", "Erickson")

# ✅ Clave panel
CLAVE_BARBERO = os.getenv("CLAVE_BARBERO", "1234")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# =========================
# Anti-duplicados webhook
# =========================
PROCESADOS = {}
TTL_MSG = 60 * 10

# =========================
# Helpers
# =========================
def normalizar_barbero(barbero: str) -> str:
    if not barbero:
        return ""
    barbero = " ".join(barbero.strip().split())
    return barbero.title()


def es_numero_whatsapp(valor: str) -> bool:
    if not valor:
        return False
    s = str(valor).strip()
    return s.isdigit() and len(s) >= 8


def barbero_autenticado() -> bool:
    return request.cookies.get("clave_barbero") == CLAVE_BARBERO


def _precio_a_int(valor):
    if valor is None:
        return 0
    s = str(valor).replace("₡", "").replace(",", "").strip()
    try:
        return int(float(s))
    except:
        return 0

# =========================
# Servicios
# =========================
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000,
}

# =========================
# Horas
# =========================
def generar_horas(inicio_h, inicio_m, fin_h, fin_m):
    horas = []
    t = inicio_h * 60 + inicio_m
    fin = fin_h * 60 + fin_m

    while t <= fin:
        h = t // 60
        m = t % 60
        sufijo = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        horas.append(f"{h12}:{m:02d}{sufijo}")
        t += 30

    return horas

# =========================
# TXT fallback
# =========================
def leer_citas_txt():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if not linea.strip():
                    continue
                c = linea.strip().split("|")
                if len(c) == 8:
                    id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora = c
                    citas.append({
                        "id": id_cita,
                        "cliente": cliente,
                        "cliente_id": cliente_id,
                        "barbero": barbero,
                        "servicio": servicio,
                        "precio": precio,
                        "fecha": fecha,
                        "hora": hora,
                    })
    except FileNotFoundError:
        pass
    return citas


def guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")

# =========================
# WRAPPERS
# =========================
def leer_citas():
    return leer_citas_txt()


def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

# =========================
# RUTAS
# =========================
@app.route("/")
def index():
    cliente_id = request.args.get("cliente_id") or str(uuid.uuid4())

    citas_todas = leer_citas()
    citas_cliente = [c for c in citas_todas if str(c.get("cliente_id")) == str(cliente_id)]

    resp = make_response(render_template(
        "index.html",
        servicios=servicios,
        citas=citas_cliente,
        cliente_id=cliente_id,
        numero_barbero=NUMERO_BARBERO,
        nombre_barbero=NOMBRE_BARBERO,
        hoy_iso=date.today().strftime("%Y-%m-%d")
    ))

    resp.set_cookie("cliente_id", cliente_id, max_age=60 * 60 * 24 * 365)
    return resp


@app.route("/barbero")
def barbero():
    citas = leer_citas()

    hoy = date.today().strftime("%Y-%m-%d")

    stats = {
        "cant_total": len(citas),
        "cant_activas": len([c for c in citas if c["servicio"] not in ["CITA CANCELADA", "CITA ATENDIDA"]]),
        "cant_atendidas": len([c for c in citas if c["servicio"] == "CITA ATENDIDA"]),
        "cant_canceladas": len([c for c in citas if c["servicio"] == "CITA CANCELADA"]),
        "total_atendido": sum(_precio_a_int(c["precio"]) for c in citas if c["servicio"] == "CITA ATENDIDA"),
        "solo": "hoy",
        "nombre": NOMBRE_BARBERO
    }

    return render_template("barbero.html", citas=citas, fecha_actual=hoy, stats=stats)


@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero = request.args.get("barbero")

    if not fecha or not barbero:
        return jsonify([])

    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    dia_semana = fecha_obj.weekday()

    # ❌ miércoles cerrado (quita esto si quieres que trabaje)
    if dia_semana == 2:
        return jsonify([])

    if dia_semana == 6:
        horas_base = generar_horas(9, 0, 15, 0)
    else:
        horas_base = generar_horas(9, 0, 19, 30)

    citas = leer_citas()
    ocupadas = [
        c.get("hora") for c in citas
        if str(c.get("fecha")) == str(fecha)
        and c.get("servicio") != "CITA CANCELADA"
    ]

    disponibles = [h for h in horas_base if h not in ocupadas]
    return jsonify(disponibles)


@app.route("/citas_json")
def citas_json():
    return jsonify({"citas": leer_citas()})


if __name__ == "__main__":
    app.run(debug=True)







