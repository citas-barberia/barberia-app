from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import os
import uuid
import requests
import time
import urllib.parse

TZ = ZoneInfo(os.getenv("TZ", "America/Costa_Rica"))
app = Flask(__name__)
app.secret_key = "secret_key"

# =========================
# CONFIG WHATSAPP (Meta)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "barberia123")
NUMERO_BARBERO = os.getenv("NUMERO_BARBERO", "50672314147")
DOMINIO = os.getenv("DOMINIO", "https://barberia-app-1.onrender.com")
NOMBRE_BARBERO = os.getenv("NOMBRE_BARBERO", "Junior")
CLAVE_BARBERO = os.getenv("CLAVE_BARBERO", "1234")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# =========================
# Helpers
# =========================
def normalizar_barbero(barbero: str) -> str:
    if not barbero: return ""
    barbero = " ".join(barbero.strip().split())
    return barbero.title()

def enviar_whatsapp(to_numero: str, mensaje: str) -> bool:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("⚠️ Faltan WHATSAPP_TOKEN o PHONE_NUMBER_ID")
        return False
    to_numero = str(to_numero).replace("+", "").replace(" ", "").strip()
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to_numero, "type": "text", "text": {"body": mensaje}}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        return r.status_code < 400
    except Exception as e:
        print("❌ Error enviando WhatsApp:", e)
        return False

def _precio_a_int(valor):
    if valor is None: return 0
    s = str(valor).replace("₡", "").replace(",", "").strip()
    try: return int(float(s))
    except: return 0

def _now_cr():
    return datetime.now(TZ)

# =========================
# Servicios
# =========================
servicios = {
    "Corte Difuminado": 5000,
    "Corte y Barba": 7000,
    "Corte Clasico": 4500,
    "Cejas": 1500,
    "Marcado y Barba": 3500,
    "Corte Niño": 4500,
}

# =========================
# SUPABASE Logic
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def _supabase_request(method, url, params=None, json_body=None):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.request(method=method, url=url, params=params, json=json_body, headers=headers, timeout=10)
        return r.json() if r.text else []
    except: return None

def leer_citas_fuerza_bruta():
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    # Traemos todo marzo para asegurar
    params = {"fecha": "gte.2026-03-01", "select": "*"}
    res = _supabase_request("GET", url, params=params)
    return res if res is not None else []

def leer_citas():
    return leer_citas_fuerza_bruta()

def guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    body = {
        "cliente": cliente, "cliente_id": str(cliente_id), "barbero": barbero, 
        "servicio": servicio, "precio": int(precio), "fecha": fecha, 
        "hora": hora, "duracion": int(duracion)
    }
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=10)
        return r.status_code < 400
    except: return False

def buscar_cita_por_id(id_cita):
    for c in leer_citas():
        if str(c.get("id")) == str(id_cita): return c
    return None

def cancelar_cita_por_id(id_cita):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    params = {"id": f"eq.{id_cita}"}
    requests.patch(url, params=params, json={"servicio": "CITA CANCELADA"}, headers=headers)

def marcar_atendida_por_id(id_cita):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    params = {"id": f"eq.{id_cita}"}
    requests.patch(url, params=params, json={"servicio": "CITA ATENDIDA"}, headers=headers)

# =========================
# RUTAS
# =========================
@app.route("/", methods=["GET", "POST"])
def index():
    cliente_id_url = request.args.get("cliente_id")
    cliente_id_cookie = request.cookies.get("cliente_id")
    cliente_id = cliente_id_url or cliente_id_cookie or str(uuid.uuid4())
    id_limpio = str(cliente_id).replace("506", "") if str(cliente_id).startswith("506") else str(cliente_id)

    if request.method == "POST":
        try:
            cliente = request.form.get("cliente", "").strip()
            tel_raw = request.form.get("telefono_cliente", "").strip()
            # Limpiamos número
            telefono_cliente = "506" + tel_raw if len(tel_raw) == 8 else tel_raw
            cliente_id_db = tel_raw if len(tel_raw) == 8 else tel_raw.replace("506", "")
            
            servicio = request.form.get("servicio", "").strip()
            fecha = request.form.get("fecha", "").strip()
            hora_original = request.form.get("hora", "").strip() # "09:00 AM"

            if not cliente or not servicio or not hora_original:
                flash("Por favor rellene todos los campos.")
                return redirect(url_for("index", cliente_id=cliente_id))

            # Formato hora para Supabase (HH:MM:00)
            dt_h = datetime.strptime(hora_original, "%I:%M %p")
            hora_db = dt_h.strftime("%H:%M:00")
            
            duracion = 60 if "BARBA" in servicio.upper() else 30
            precio = servicios.get(servicio, 0)

            # GUARDAR
            if guardar_cita_db(cliente, cliente_id_db, NOMBRE_BARBERO, servicio, precio, fecha, hora_db, duracion):
                # WhatsApps
                msg_c = f"✅ *¡Cita Confirmada!* 💈\n\nHola *{cliente}*, tu espacio para *{servicio}* el {fecha} a las {hora_original} está reservado.\n\nPara gestionar:\n{DOMINIO}/?cliente_id={cliente_id_db}"
                enviar_whatsapp(telefono_cliente, msg_c)
                enviar_whatsapp(NUMERO_BARBERO, f"💈 Nueva cita: {cliente}\n{servicio}\n{fecha} {hora_original}")
                
                link_wa = f"https://wa.me/{telefono_cliente}?text={urllib.parse.quote(msg_c)}"
                return render_template("confirmacion.html", link_wa=link_wa, cliente=cliente)
            else:
                flash("Error al guardar en la base de datos.")
        except Exception as e:
            print(f"Error POST: {e}")
            flash("Error interno del servidor.")

    citas_todas = leer_citas()
    citas_cliente = [c for c in citas_todas if str(c.get("cliente_id", "")) in [str(cliente_id), id_limpio] and "CANCELADA" not in str(c.get("servicio")).upper()]

    resp = make_response(render_template("index.html", servicios=servicios, citas=citas_cliente, cliente_id=cliente_id, numero_barbero=NUMERO_BARBERO, nombre_barbero=NOMBRE_BARBERO, hoy_iso=_now_cr().strftime("%Y-%m-%d")))
    resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
    return resp

@app.route("/horas")
def horas():
    try:
        fecha_str = request.args.get('fecha')
        if not fecha_str: return jsonify([])
        f_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        ahora_cr = datetime.now(TZ).replace(tzinfo=None)

        dia = f_obj.weekday()
        h_i, h_f = (9, 16) if dia == 6 else ((8, 20) if dia in [4, 5] else (9, 20))

        horas_base = []
        temp = datetime.combine(f_obj, datetime.min.time()).replace(hour=h_i)
        fin = datetime.combine(f_obj, datetime.min.time()).replace(hour=h_f)
        while temp < fin:
            horas_base.append(temp.strftime("%H:%M:00"))
            temp += timedelta(minutes=30)

        citas = leer_citas_fuerza_bruta()
        ocupadas = set()
        for c in citas:
            if str(c.get("fecha")) == fecha_str and "CANCELADA" not in str(c.get("servicio")).upper():
                h_db = str(c.get("hora"))
                ocupadas.add(h_db)
                if int(c.get("duracion", 30)) > 30:
                    try:
                        dt = datetime.strptime(h_db, "%H:%M:%S")
                        ocupadas.add((dt + timedelta(minutes=30)).strftime("%H:%M:%S"))
                    except: pass

        res = []
        for h in horas_base:
            h_dt = datetime.strptime(h, "%H:%M:%S")
            if datetime.combine(f_obj, h_dt.time()) > (ahora_cr + timedelta(minutes=10)):
                if h not in ocupadas:
                    res.append(h_dt.strftime("%I:%M %p").upper().lstrip('0'))
        return jsonify(res)
    except: return jsonify([])

# Las demás rutas (/cancelar, /barbero, etc) se mantienen igual que antes
@app.route("/barbero")
def barbero():
    clave = request.args.get("clave")
    if request.cookies.get("clave_barbero") == CLAVE_BARBERO or clave == CLAVE_BARBERO:
        citas = leer_citas()
        # ... (Toda tu lógica de stats)
        resp = make_response(render_template("barbero.html", citas=citas, stats={"nombre": NOMBRE_BARBERO}))
        resp.set_cookie("clave_barbero", CLAVE_BARBERO)
        return resp
    return "🔒"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
