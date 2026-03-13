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

PROCESADOS = {}
TTL_MSG = 60 * 10 

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
        print("📤 WhatsApp -> to:", to_numero, "| status:", r.status_code)
        return r.status_code < 400
    except Exception as e:
        print("❌ Error enviando WhatsApp:", e)
        return False

def es_numero_whatsapp(valor: str) -> bool:
    if not valor: return False
    s = str(valor).strip()
    return s.isdigit() and len(s) >= 8

def barbero_autenticado() -> bool:
    return request.cookies.get("clave_barbero") == CLAVE_BARBERO

def _precio_a_int(valor):
    if valor is None: return 0
    s = str(valor).replace("₡", "").replace(",", "").strip()
    try: return int(float(s))
    except: return 0

def _hora_ampm_a_time(hora_str: str):
    if not hora_str: return None
    s = str(hora_str).strip().lower().replace(" ", "")
    try: return datetime.strptime(s, "%I:%M%p").time()
    except: return None

def _cita_a_datetime(fecha_str: str, hora_str: str):
    if not fecha_str or not hora_str: return None
    try:
        t = _hora_ampm_a_time(hora_str)
        if not t: return None
        dt = datetime.strptime(str(fecha_str), "%Y-%m-%d")
        dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        return dt.replace(tzinfo=TZ)
    except: return None

def _now_cr():
    return datetime.now(TZ)

# =========================
# Servicios y horas
# =========================
servicios = {
    "Corte Difuminado": 5000,
    "Corte y Barba": 7000,
    "Corte Clasico": 4500,
    "Cejas": 1500,
    "Marcado y Barba": 3500,
    "Corte Niño": 4500,
}

def generar_horas(inicio_h, inicio_m, fin_h, fin_m):
    horas = []
    t, fin = inicio_h * 60 + inicio_m, fin_h * 60 + fin_m
    while t <= fin:
        h, m = t // 60, t % 60
        sufijo = "am" if h < 12 else "pm"
        h12 = 12 if h % 12 == 0 else h % 12
        horas.append(f"{h12}:{m:02d}{sufijo}")
        t += 30
    return horas

HORAS_BASE = generar_horas(8, 0, 19, 30)

# =========================
# SUPABASE & TXT Logic
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
USAR_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
SUPABASE_TIMEOUT = int(os.getenv("SUPABASE_TIMEOUT", "10"))

def _supabase_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Accept": "application/json"}

def _supabase_request(method, url, params=None, json_body=None, extra_headers=None):
    headers = _supabase_headers()
    if extra_headers: headers.update(extra_headers)
    try:
        r = requests.request(method=method, url=url, params=params, json=json_body, headers=headers, timeout=SUPABASE_TIMEOUT)
        r.raise_for_status()
        return r.json() if r.text else None
    except Exception as e:
        print(f"⚠️ Supabase falló:", e)
        return None

def leer_citas_txt():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if not linea.strip(): continue
                c = linea.strip().split("|")
                if len(c) == 8:
                    citas.append({"id": c[0], "cliente": c[1], "cliente_id": c[2], "barbero": c[3], "servicio": c[4], "precio": c[5], "fecha": c[6], "hora": c[7]})
    except FileNotFoundError: pass
    return citas

def guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")

def _reescribir_citas_txt_actualizando_servicio(id_cita, nuevo_servicio):
    citas = leer_citas_txt()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            cid = c.get("id") or str(uuid.uuid4())
            srv = nuevo_servicio if str(cid) == str(id_cita) else c['servicio']
            f.write(f"{cid}|{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{srv}|{c['precio']}|{c['fecha']}|{c['hora']}\n")

def leer_citas_db():
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    data = _supabase_request("GET", url, params={"select": "*"})
    if data is None: return None
    return [{"id": r.get("id"), "cliente": r.get("cliente", ""), "cliente_id": r.get("cliente_id", ""), "barbero": r.get("barbero", ""), "servicio": r.get("servicio", ""), "precio": str(r.get("precio", "")), "fecha": str(r.get("fecha", "")), "hora": str(r.get("hora", ""))} for r in data]

def guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    body = {"cliente": cliente, "cliente_id": str(cliente_id), "barbero": barbero, "servicio": servicio, "precio": int(precio), "fecha": fecha, "hora": hora}
    res = _supabase_request("POST", url, json_body=body, extra_headers={"Prefer": "return=minimal"})
    return res is not None or True

def leer_citas():
    if USAR_SUPABASE:
        data = leer_citas_db()
        if data is not None: return data
    return leer_citas_txt()

def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        try:
            if not guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
                guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)
        except: guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)
    else: guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

def cancelar_cita_por_id(id_cita):
    if USAR_SUPABASE:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
        _supabase_request("PATCH", url, params={"id": f"eq.{id_cita}"}, json_body={"servicio": "CITA CANCELADA"})
    _reescribir_citas_txt_actualizando_servicio(id_cita, "CITA CANCELADA")

def marcar_atendida_por_id(id_cita):
    if USAR_SUPABASE:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
        _supabase_request("PATCH", url, params={"id": f"eq.{id_cita}"}, json_body={"servicio": "CITA ATENDIDA"})
    _reescribir_citas_txt_actualizando_servicio(id_cita, "CITA ATENDIDA")

def buscar_cita_por_id(id_cita):
    for c in leer_citas():
        if str(c.get("id")) == str(id_cita): return c
    return None

# =========================
# RUTAS
# =========================
@app.route("/", methods=["GET", "POST"])
def index():
    cliente_id_url = request.args.get("cliente_id")
    cliente_id_cookie = request.cookies.get("cliente_id")
    cliente_id = cliente_id_url or cliente_id_cookie or str(uuid.uuid4())

    hoy_dt = _now_cr()
    citas_todas = leer_citas()
    mes_actual = hoy_dt.strftime("%Y-%m")
    citas_cliente = [c for c in citas_todas if str(c.get("cliente_id", "")) == str(cliente_id) and str(c.get("fecha", "")).startswith(mes_actual)]

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        tel_raw = request.form.get("telefono_cliente", "").strip()
        telefono_cliente = "506" + tel_raw if len(tel_raw) == 8 else tel_raw
        
        barbero_raw = request.form.get("barbero", "").strip()
        servicio = request.form.get("servicio", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        cliente_id = telefono_cliente 
        barbero = normalizar_barbero(barbero_raw)
        precio = str(servicios.get(servicio, 0))

        conflict = any(normalizar_barbero(c.get("barbero", "")) == barbero and str(c.get("fecha")) == fecha and str(c.get("hora")) == hora and c.get("servicio") != "CITA CANCELADA" for c in citas_todas)

        if conflict:
            flash("La hora seleccionada ya está ocupada.")
            return redirect(url_for("index", cliente_id=cliente_id))

        id_cita = str(uuid.uuid4())
        guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

        # Avisar a Junior
        msg_barbero = f"💈 Nueva cita agendada\n\nCliente: {cliente}\nServicio: {servicio}\nFecha: {fecha}\nHora: {hora}\nPrecio: ₡{precio}"
        enviar_whatsapp(NUMERO_BARBERO, msg_barbero)

        # Preparar link de WhatsApp para el cliente
        msg_cliente = f"✅ *¡Cita Confirmada!* 💈\n\nHola *{cliente}*, tu espacio para *{servicio}* el {fecha} a las {hora} está reservado.\n\nPara gestionar o cancelar:\n{DOMINIO}/?cliente_id={telefono_cliente}"
        link_wa = f"https://wa.me/{telefono_cliente}?text={urllib.parse.quote(msg_cliente)}"
        return render_template("confirmacion.html", link_wa=link_wa, cliente=cliente)

    resp = make_response(render_template("index.html", servicios=servicios, citas=citas_cliente, cliente_id=cliente_id, numero_barbero=NUMERO_BARBERO, nombre_barbero=NOMBRE_BARBERO, hoy_iso=hoy_dt.strftime("%Y-%m-%d")))
    resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
    return resp

@app.route("/cancelar", methods=["POST"])
def cancelar():
    id_cita = request.form.get("id")
    cita = buscar_cita_por_id(id_cita)
    if not cita: return redirect(url_for("index"))

    cancelar_cita_por_id(id_cita)
    cliente_id = str(cita.get("cliente_id", ""))
    
    # Notificar
    enviar_whatsapp(NUMERO_BARBERO, f"❌ Cita CANCELADA: {cita.get('cliente')} el {cita.get('fecha')} a las {cita.get('hora')}")
    if es_numero_whatsapp(cliente_id):
        enviar_whatsapp(cliente_id, f"Tu cita del {cita.get('fecha')} ha sido cancelada. Ya puedes agendar de nuevo.")

    flash("Cita cancelada correctamente")
    if barbero_autenticado(): return redirect(url_for("barbero"))
    resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
    resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
    return resp

@app.route("/atendida", methods=["POST"])
def atendida():
    if barbero_autenticado(): marcar_atendida_por_id(request.form.get("id"))
    return redirect(url_for("barbero"))

@app.route("/barbero", methods=["GET"])
def barbero():
    clave = request.args.get("clave")
    if barbero_autenticado() or clave == CLAVE_BARBERO:
        resp = make_response(_render_panel_barbero())
        resp.set_cookie("clave_barbero", CLAVE_BARBERO, max_age=60*60*24*7)
        return resp
    return "🔒 Panel protegido."

def _render_panel_barbero():
    citas = leer_citas()
    solo, estado, q = request.args.get("solo", "hoy"), request.args.get("estado", "activas"), (request.args.get("q") or "").strip().lower()
    # (Tus filtros de panel barbero se mantienen en el barbero.html vía JS)
    stats = {"cant_total": len(citas), "cant_activas": sum(1 for c in citas if c.get("servicio") not in ["CITA CANCELADA", "CITA ATENDIDA"]), "total_atendido": sum(_precio_a_int(c.get("precio")) for c in citas if c.get("servicio") == "CITA ATENDIDA"), "nombre": NOMBRE_BARBERO}
    return render_template("barbero.html", citas=citas, stats=stats)

@app.route("/horas")
def horas():
    fecha, barbero = request.args.get("fecha"), request.args.get("barbero")
    if not fecha or not barbero: return jsonify([])
    
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    dia = fecha_obj.weekday()
    if dia <= 3: horas_base = generar_horas(9, 0, 20, 0)
    elif dia <= 5: horas_base = generar_horas(8, 0, 20, 0)
    else: horas_base = generar_horas(9, 0, 16, 0)

    barbero_norm = normalizar_barbero(barbero)
    citas = leer_citas()
    ocupadas = [c.get("hora") for c in citas if normalizar_barbero(c.get("barbero", "")) == barbero_norm and str(c.get("fecha")) == str(fecha) and c.get("servicio") != "CITA CANCELADA"]
    
    disponibles = [h for h in horas_base if h not in ocupadas]
    # Bloquear horas pasadas si es hoy
    if str(fecha) == _now_cr().strftime("%Y-%m-%d"):
        ahora_min = _now_cr().hour * 60 + _now_cr().minute
        disponibles = [h for h in disponibles if (_hora_ampm_a_time(h).hour * 60 + _hora_ampm_a_time(h).minute) > ahora_min]
    return jsonify(disponibles)

@app.route("/citas_json")
def citas_json():
    return jsonify({"citas": leer_citas()})

if __name__ == "__main__":
    app.run(debug=True)




