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
    # Limpiamos el texto: quitamos espacios y lo pasamos a minúsculas
    s = str(hora_str).strip().lower().replace(" ", "")
    
    # Intentamos formato 12h (08:00am, 1:30pm)
    try:
        if "am" in s or "pm" in s:
            return datetime.strptime(s, "%I:%M%p").time()
    except: pass

    # Intentamos formato 24h (08:00, 13:30)
    try:
        return datetime.strptime(s, "%H:%M").time()
    except: pass

    # Si llega con segundos (algunas DB lo mandan así: 13:30:00)
    try:
        return datetime.strptime(s, "%H:%M:%S").time()
    except: pass

    return None
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
                if len(c) >= 8:
                    dur = c[8] if len(c) == 9 else "30"
                    citas.append({
                        "id": c[0], "cliente": c[1], "cliente_id": c[2], 
                        "barbero": c[3], "servicio": c[4], "precio": c[5], 
                        "fecha": c[6], "hora": c[7], "duracion": dur
                    })
    except FileNotFoundError: pass
    return citas
def leer_citas_fuerza_bruta():
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        # Traemos citas desde ayer para asegurar que no se escape nada de hoy/mañana
        import datetime
        inicio = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        url_filtered = f"{url}?fecha=gte.{inicio}"

        import requests
        response = requests.get(url_filtered, headers=headers)
        return response.json() if response.status_code == 200 else []
    except:
        return []
def guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}|{duracion}\n")

def leer_citas_db():
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    
    # Optimizamos: Traemos solo lo necesario para que cargue rápido (Punto 5)
    hoy = _now_cr()
    inicio_mes = hoy.replace(day=1).strftime("%Y-%m-%d")
    
    params = {
        "select": "*",
        "fecha": f"gte.{inicio_mes}",
        "order": "fecha.asc,hora.asc"
    }
    
    data = _supabase_request("GET", url, params=params)
    if data is None: return None
    
    citas_procesadas = []
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    
    for r in data:
        # Hora bonita
        hora_raw = str(r.get("hora", ""))
        try:
            h_obj = datetime.strptime(hora_raw, "%H:%M")
            hora_bonita = h_obj.strftime("%I:%M %p").lower()
        except:
            hora_bonita = hora_raw

        # Fecha bonita con día
        f_raw = str(r.get("fecha", ""))
        try:
            f_obj = datetime.strptime(f_raw, "%Y-%m-%d")
            fecha_bonita = f"{dias_semana[f_obj.weekday()]} {f_obj.strftime('%d/%m/%Y')}"
        except:
            fecha_bonita = f_raw

        citas_procesadas.append({
            "id": r.get("id"),
            "cliente": r.get("cliente", ""),
            "cliente_id": r.get("cliente_id", ""),
            "barbero": r.get("barbero", ""),
            "servicio": r.get("servicio", ""),
            "precio": r.get("precio", 0),
            "fecha": fecha_bonita,
            "fecha_iso": f_raw, # Guardamos la original para filtros exactos
            "hora": hora_bonita,
            "duracion": str(r.get("duracion", "30"))
        })
    return citas_procesadas

def guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
    body = {
        "cliente": cliente, "cliente_id": str(cliente_id), "barbero": barbero, 
        "servicio": servicio, "precio": int(precio), "fecha": fecha, 
        "hora": hora, "duracion": int(duracion)
    }
    res = _supabase_request("POST", url, json_body=body, extra_headers={"Prefer": "return=minimal"})
    return res is not None

def leer_citas():
    # Siempre intentamos leer de DB primero para tener el orden correcto
    if USAR_SUPABASE:
        data = leer_citas_db()
        if data is not None: return data
    return leer_citas_txt()

def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion):
    if USAR_SUPABASE:
        try:
            if not guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion):
                guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion)
        except: 
            guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion)
    else: 
        guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora, duracion)

def _reescribir_citas_txt_actualizando_servicio(id_cita, nuevo_servicio):
    citas = leer_citas_txt()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            cid = c.get("id")
            srv = nuevo_servicio if str(cid) == str(id_cita) else c['servicio']
            f.write(f"{cid}|{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{srv}|{c['precio']}|{c['fecha']}|{c['hora']}|{c.get('duracion','30')}\n")

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
    # 1. Obtener el ID del cliente de URL o Cookie
    cliente_id_url = request.args.get("cliente_id")
    cliente_id_cookie = request.cookies.get("cliente_id")
    cliente_id = cliente_id_url or cliente_id_cookie or str(uuid.uuid4())

    # 2. Limpiar el ID para la búsqueda (quitar el 506 si viene en el link)
    # Así, si el link trae 50672314147, también buscará como 72314147
    id_limpio = str(cliente_id).replace("506", "") if str(cliente_id).startswith("506") else str(cliente_id)

    citas_todas = leer_citas()
    
    # 3. Buscamos citas que coincidan con el ID completo O el ID sin el 506
    citas_cliente = [
        c for c in citas_todas 
        if (str(c.get("cliente_id", "")) == str(cliente_id) or str(c.get("cliente_id", "")) == id_limpio)
        and c.get("servicio") not in ["CITA CANCELADA", "CITA ATENDIDA"]
    ]

    if request.method == "POST":
        # ... (Tu código de guardado de cita se mantiene igual) ...
        # Solo asegúrate de que al guardar, uses el cliente_id que el usuario tiene
        pass

    resp = make_response(render_template("index.html", 
        servicios=servicios, 
        citas=citas_cliente, 
        cliente_id=cliente_id, 
        numero_barbero=NUMERO_BARBERO, 
        nombre_barbero=NOMBRE_BARBERO, 
        hoy_iso=_now_cr().strftime("%Y-%m-%d")
    ))
    
    # Guardamos la cookie para que no tenga que loguearse siempre
    resp.set_cookie("cliente_id", cliente_id, max_age=60*60*24*365)
    return resp

def leer_citas_fuerza_bruta():
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/citas"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        # Traemos TODO lo de marzo para no fallar
        url_filtered = f"{url}?fecha=gte.2026-03-01&select=*"

        r = requests.get(url_filtered, headers=headers, timeout=10)
        data = r.json() if r.status_code == 200 else []
        
        # ESTO ES VITAL: Vamos a ver en los logs qué está llegando
        print(f"DEBUG: Se encontraron {len(data)} citas en Supabase")
        return data
    except Exception as e:
        print(f"❌ ERROR LEYENDO DB: {e}")
        return []

@app.route("/horas")
def horas():
    try:
        fecha_str = request.args.get('fecha') # "2026-03-22"
        if not fecha_str: return jsonify([])

        f_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        ahora_cr = datetime.now(TZ).replace(tzinfo=None)

        # 1. Horario Domingo: 9:00 AM a 4:00 PM
        dia_semana = f_obj.weekday()
        if dia_semana == 6: h_i, h_f = 9, 16
        elif dia_semana in [4, 5]: h_i, h_f = 8, 20
        else: h_i, h_f = 9, 20

        # 2. Generar todas las horas posibles
        horas_base = []
        temp = datetime.combine(f_obj, datetime.min.time()).replace(hour=h_i)
        fin = datetime.combine(f_obj, datetime.min.time()).replace(hour=h_f)
        while temp < fin:
            horas_base.append(temp.strftime("%H:%M:00")) # Formato DB "09:00:00"
            temp += timedelta(minutes=30)

        # 3. Leer citas y marcar SOLO las ocupadas
        citas = leer_citas_fuerza_bruta()
        ocupadas = set()
        
        for c in citas:
            # Validar fecha y que la cita no esté cancelada
            if str(c.get("fecha")) == fecha_str and "CANCELADA" not in str(c.get("servicio")).upper():
                h_db = str(c.get("hora")) # Ej: "10:00:00"
                ocupadas.add(h_db)
                
                # SOLO si es "Corte y Barba" bloqueamos el siguiente espacio
                # (Porque dura 1 hora, los demás duran 30 min)
                if "BARBA" in str(c.get("servicio")).upper():
                    try:
                        dt_h = datetime.strptime(h_db, "%H:%M:%S")
                        prox = (dt_h + timedelta(minutes=30)).strftime("%H:%M:%S")
                        ocupadas.add(prox)
                    except: pass

        # 4. Filtrar y mostrar al cliente
        res = []
        for h in horas_base:
            h_dt = datetime.strptime(h, "%H:%M:%S")
            # Si no ha pasado la hora (margen 10 min) y NO está en ocupadas
            if datetime.combine(f_obj, h_dt.time()) > (ahora_cr + timedelta(minutes=10)):
                if h not in ocupadas:
                    res.append(h_dt.strftime("%I:%M %p").upper().lstrip('0'))
        
        return jsonify(res)
    except Exception as e:
        print(f"Error: {e}")
        return jsonify([])
@app.route("/cancelar", methods=["POST"])
def cancelar():
    id_cita = request.form.get("id")
    cita = buscar_cita_por_id(id_cita)
    
    if not cita: 
        return redirect(url_for("index"))

    # Paso 1: Cancelar la cita de una vez (esto es rápido)
    cancelar_cita_por_id(id_cita)
    
    # Paso 2: El envío de WhatsApp suele ser lento. 
    # Lo metemos en un try para que si falla el servicio, no bloquee la pantalla de Junior.
    try:
        enviar_whatsapp(NUMERO_BARBERO, f"❌ Cita CANCELADA: {cita.get('cliente')} el {cita.get('fecha')} a las {cita.get('hora')}")
    except Exception as e:
        print(f"Error enviando WhatsApp: {e}") # Solo lo logueamos, no detenemos el proceso.

    flash("Cita cancelada correctamente")
    
    # Paso 3: Redirigir de inmediato para que la página cargue de nuevo.
    if barbero_autenticado(): 
        return redirect(url_for("barbero"))
    
    cliente_id = str(cita.get("cliente_id", ""))
    return redirect(url_for("index", cliente_id=cliente_id))

@app.route("/atendida", methods=["POST"])
def atendida():
    id_cita = request.form.get("id")
    if barbero_autenticado() and id_cita:
        marcar_atendida_por_id(id_cita)
        flash("¡Cita completada!") # Agregamos un flash para que Junior vea que sí funcionó
    
    return redirect(url_for("barbero"))

@app.route("/barbero", methods=["GET"])
def barbero():
    clave = request.args.get("clave")
    if barbero_autenticado() or clave == CLAVE_BARBERO:
        citas = leer_citas()
        hoy_iso = _now_cr().strftime("%Y-%m-%d")
        
        # Filtramos solo las de hoy para los stats iniciales
        citas_hoy = [c for c in citas if c.get("fecha_iso") == hoy_iso]
        
        stats = {
            "cant_total": len(citas_hoy),
            "cant_activas": sum(1 for c in citas_hoy if c.get("servicio") not in ["CITA CANCELADA", "CITA ATENDIDA"]),
            "cant_atendidas": sum(1 for c in citas_hoy if c.get("servicio") == "CITA ATENDIDA"),
            "cant_canceladas": sum(1 for c in citas_hoy if c.get("servicio") == "CITA CANCELADA"),
            "total_atendido": sum(_precio_a_int(c.get("precio")) for c in citas_hoy if c.get("servicio") == "CITA ATENDIDA"),
            "nombre": NOMBRE_BARBERO
        }
        
        resp = make_response(render_template("barbero.html", citas=citas, stats=stats))
        resp.set_cookie("clave_barbero", CLAVE_BARBERO, max_age=60*60*24*7)
        return resp
    return "🔒 Panel protegido."

@app.route("/citas_json")
def citas_json():
    return jsonify({"citas": leer_citas()})

if __name__ == "__main__":
    # Importante para que Render detecte el puerto correctamente
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

