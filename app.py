from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import date, timedelta, datetime
import os
import uuid
import requests
import time

app = Flask(__name__)
app.secret_key = "secret_key"

# =========================
# CONFIG WHATSAPP (Meta)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "barberia123")
NUMERO_BARBERO = os.getenv("NUMERO_BARBERO", "50672314147")
DOMINIO = os.getenv("DOMINIO", "https://barberia-app-1.onrender.com")
NOMBRE_BARBERO = os.getenv("NOMBRE_BARBERO", "Erickson")
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
    return " ".join(barbero.strip().split()).title()

def enviar_whatsapp(to_numero: str, mensaje: str) -> bool:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID: return False
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to_numero, "type": "text", "text": {"body": mensaje}}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        return r.status_code < 400
    except: return False

def es_numero_whatsapp(valor: str) -> bool:
    s = str(valor or "").strip()
    return s.isdigit() and len(s) >= 8

def barbero_autenticado() -> bool:
    return request.cookies.get("clave_barbero") == CLAVE_BARBERO

def _precio_a_int(valor):
    s = str(valor or "0").replace("₡", "").replace(",", "").strip()
    try: return int(float(s))
    except: return 0

# =========================
# Servicios y horas
# =========================
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000,
}

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

# ==========================================================
# GESTIÓN DE DATOS (TXT + SUPABASE FALLBACK)
# ==========================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
USAR_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
SUPABASE_TIMEOUT = 10

def leer_citas():
    citas = []
    # Prioridad Supabase si está configurado
    if USAR_SUPABASE:
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            r = requests.get(url, headers=headers, timeout=SUPABASE_TIMEOUT)
            if r.status_code == 200:
                for row in r.json():
                    citas.append({
                        "id": row.get("id"), "cliente": row.get("cliente"),
                        "cliente_id": row.get("cliente_id"), "barbero": row.get("barbero"),
                        "servicio": row.get("servicio"), "precio": str(row.get("precio")),
                        "fecha": str(row.get("fecha")), "hora": str(row.get("hora"))
                    })
                return citas
        except: pass
    
    # Fallback a TXT
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                c = linea.strip().split("|")
                if len(c) >= 7:
                    citas.append({
                        "id": c[0], "cliente": c[1], "cliente_id": c[2],
                        "barbero": c[3], "servicio": c[4], "precio": c[5],
                        "fecha": c[6], "hora": c[7] if len(c)>7 else ""
                    })
    except FileNotFoundError: pass
    return citas

def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
            body = {"cliente": cliente, "cliente_id": str(cliente_id), "barbero": barbero, "servicio": servicio, "precio": int(precio), "fecha": fecha, "hora": hora}
            requests.post(url, headers=headers, json=body, timeout=SUPABASE_TIMEOUT)
        except: pass
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")

def buscar_cita_por_id(id_cita):
    for c in leer_citas():
        if str(c.get("id")) == str(id_cita): return c
    return None

def actualizar_estado_cita(id_cita, nuevo_estado):
    citas = leer_citas()
    if USAR_SUPABASE:
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas?id=eq.{id_cita}"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
            requests.patch(url, headers=headers, json={"servicio": nuevo_estado}, timeout=SUPABASE_TIMEOUT)
        except: pass
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            srv = nuevo_estado if str(c['id']) == str(id_cita) else c['servicio']
            f.write(f"{c['id']}|{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{srv}|{c['precio']}|{c['fecha']}|{c['hora']}\n")

# =========================
# RUTAS
# =========================
@app.route("/", methods=["GET", "POST"])
def index():
    cliente_id = request.args.get("cliente_id") or request.cookies.get("cliente_id") or str(uuid.uuid4())
    citas_todas = leer_citas()

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        barbero = normalizar_barbero(request.form.get("barbero", NOMBRE_BARBERO))
        servicio = request.form.get("servicio", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()
        precio = str(servicios.get(servicio, 0))

        # Evitar duplicados
        if any(normalizar_barbero(c['barbero']) == barbero and c['fecha'] == fecha and c['hora'] == hora and c['servicio'] not in ["CITA CANCELADA", "CITA ATENDIDA"] for c in citas_todas):
            flash("Esa hora ya se ocupó. Elige otra.")
            return redirect(url_for("index", cliente_id=cliente_id))

        id_cita = str(uuid.uuid4())
        guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)
        
        # Notificaciones
        enviar_whatsapp(NUMERO_BARBERO, f"💈 Nueva cita: {cliente} - {hora}")
        if es_numero_whatsapp(cliente_id):
            enviar_whatsapp(cliente_id, f"✅ Cita confirmada: {fecha} a las {hora}")

        flash("Cita agendada exitosamente")
        resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
        resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
        return resp

    citas_cliente = [c for c in citas_todas if str(c.get("cliente_id")) == str(cliente_id)]
    hoy_iso = date.today().strftime("%Y-%m-%d")
    
    resp = make_response(render_template("index.html", servicios=servicios, citas=citas_cliente, cliente_id=cliente_id, nombre_barbero=NOMBRE_BARBERO, hoy_iso=hoy_iso))
    resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
    return resp

@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero = normalizar_barbero(request.args.get("barbero") or NOMBRE_BARBERO)
    if not fecha: return jsonify([])

    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    dia = fecha_obj.weekday()
    
    # Horarios según tu lógica original
    if dia == 2: return jsonify([]) # Miércoles cerrado
    horas_base = generar_horas(9, 0, 15, 0) if dia == 6 else generar_horas(9, 0, 19, 30)

    ocupadas = [c.get("hora") for c in leer_citas() if normalizar_barbero(c.get("barbero")) == barbero and c.get("fecha") == fecha and c.get("servicio") not in ["CITA CANCELADA", "CITA ATENDIDA"]]
    
    return jsonify([h for h in horas_base if h not in ocupadas])

@app.route("/cancelar", methods=["POST"])
def cancelar():
    id_cita = request.form.get("id")
    actualizar_estado_cita(id_cita, "CITA CANCELADA")
    flash("Cita cancelada")
    return redirect(url_for("index"))

@app.route("/atendida", methods=["POST"])
def atendida():
    if not barbero_autenticado(): return redirect(url_for("barbero"))
    actualizar_estado_cita(request.form.get("id"), "CITA ATENDIDA")
    return redirect(url_for("barbero"))

@app.route("/barbero")
def barbero():
    if request.args.get("clave") == CLAVE_BARBERO or barbero_autenticado():
        citas = leer_citas()
        # Aquí puedes simplificar las stats como tenías antes
        hoy = date.today().strftime("%Y-%m-%d")
        citas_hoy = [c for c in citas if c['fecha'] == hoy]
        stats = {"cant_total": len(citas_hoy), "nombre": NOMBRE_BARBERO, "cant_activas": sum(1 for c in citas_hoy if c['servicio'] not in ["CITA CANCELADA", "CITA ATENDIDA"]), "total_atendido": sum(_precio_a_int(c['precio']) for c in citas_hoy if c['servicio'] == "CITA ATENDIDA")}
        
        resp = make_response(render_template("barbero.html", citas=citas_hoy, stats=stats))
        resp.set_cookie("clave_barbero", CLAVE_BARBERO)
        return resp
    return "Acceso denegado"

@app.route("/citas_json")
def citas_json():
    return jsonify({"citas": leer_citas()})

if __name__ == "__main__":
    app.run(debug=True)









