from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import date, timedelta
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

# ✅ Nombre del barbero (Ericson)
NOMBRE_BARBERO = os.getenv("NOMBRE_BARBERO", "Ericson")

# ✅ Clave para entrar al panel del barbero
CLAVE_BARBERO = os.getenv("CLAVE_BARBERO", "1234")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# =========================
# Anti-duplicados webhook
# =========================
PROCESADOS = {}  # {message_id: timestamp}
TTL_MSG = 60 * 10  # 10 minutos


# =========================
# Helpers
# =========================
def normalizar_barbero(barbero: str) -> str:
    if not barbero:
        return ""
    barbero = " ".join(barbero.strip().split())
    return barbero.title()


def enviar_whatsapp(to_numero: str, mensaje: str) -> bool:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("⚠️ Faltan WHATSAPP_TOKEN o PHONE_NUMBER_ID en variables de entorno")
        return False

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_numero,
        "type": "text",
        "text": {"body": mensaje},
    }

    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        if r.status_code >= 400:
            print("❌ Error WhatsApp:", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        print("❌ Error enviando WhatsApp:", e)
        return False


def es_numero_whatsapp(valor: str) -> bool:
    if not valor:
        return False
    s = str(valor).strip()
    return s.isdigit() and len(s) >= 8


def barbero_autenticado() -> bool:
    """✅ Si el barbero ya metió la clave, queda guardada en cookie."""
    return request.cookies.get("clave_barbero") == CLAVE_BARBERO


# =========================
# Servicios y horas
# =========================
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000,
}

HORAS_BASE = ["09:00am", "10:00am", "11:00am", "12:00md", "1:00pm", "2:00pm", "3:00pm", "4:00pm", "5:00pm"]


# =========================
# SUPABASE (SQL)
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = None
USAR_SUPABASE = False

if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        USAR_SUPABASE = True
        print("✅ Supabase conectado")
    except Exception as e:
        print("⚠️ No se pudo iniciar Supabase. Se usará citas.txt. Error:", e)
        USAR_SUPABASE = False
else:
    print("⚠️ Faltan SUPABASE_URL / SUPABASE_KEY. Se usará citas.txt.")


# ==========================================================
# RESPALDO TXT
# ==========================================================
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
                    continue

                if len(c) == 7:
                    cliente, cliente_id, barbero, servicio, precio, fecha, hora = c
                    citas.append({
                        "id": None,
                        "cliente": cliente,
                        "cliente_id": cliente_id,
                        "barbero": barbero,
                        "servicio": servicio,
                        "precio": precio,
                        "fecha": fecha,
                        "hora": hora,
                    })
                    continue

    except FileNotFoundError:
        pass

    return citas


def guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{id_cita}|{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")


def _reescribir_citas_txt_actualizando_servicio(id_cita, nuevo_servicio):
    citas = leer_citas_txt()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            cid = c.get("id") or str(uuid.uuid4())
            servicio = c.get("servicio")
            if str(cid) == str(id_cita):
                servicio = nuevo_servicio
            f.write(f"{cid}|{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{servicio}|{c['precio']}|{c['fecha']}|{c['hora']}\n")


def cancelar_cita_txt_por_id(id_cita):
    _reescribir_citas_txt_actualizando_servicio(id_cita, "CITA CANCELADA")


def marcar_atendida_txt_por_id(id_cita):
    _reescribir_citas_txt_actualizando_servicio(id_cita, "CITA ATENDIDA")


def buscar_cita_txt_por_id(id_cita):
    for c in leer_citas_txt():
        if str(c.get("id")) == str(id_cita):
            return c
    return None


# ==========================================================
# SUPABASE DB
# ==========================================================
def leer_citas_db():
    try:
        res = supabase.table("citas").select("*").execute()
        data = res.data if res and res.data else []
        citas = []
        for r in data:
            citas.append({
                "id": r.get("id"),
                "cliente": r.get("cliente", ""),
                "cliente_id": r.get("cliente_id", ""),
                "barbero": r.get("barbero", ""),
                "servicio": r.get("servicio", ""),
                "precio": str(r.get("precio", "")),
                "fecha": str(r.get("fecha", "")),
                "hora": str(r.get("hora", "")),
            })
        return citas
    except Exception as e:
        print("Error leer_citas_db:", e)
        return []


def guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    try:
        supabase.table("citas").insert({
            "cliente": cliente,
            "cliente_id": str(cliente_id),
            "barbero": barbero,
            "servicio": servicio,
            "precio": int(precio),
            "fecha": fecha,
            "hora": hora
        }).execute()
        return True
    except Exception as e:
        print("Error guardar_cita_db:", e)
        return False


def buscar_cita_db_por_id(id_cita):
    try:
        res = supabase.table("citas").select("*").eq("id", id_cita).limit(1).execute()
        data = res.data if res and res.data else []
        if not data:
            return None
        r = data[0]
        return {
            "id": r.get("id"),
            "cliente": r.get("cliente", ""),
            "cliente_id": r.get("cliente_id", ""),
            "barbero": r.get("barbero", ""),
            "servicio": r.get("servicio", ""),
            "precio": str(r.get("precio", "")),
            "fecha": str(r.get("fecha", "")),
            "hora": str(r.get("hora", "")),
        }
    except Exception as e:
        print("Error buscar_cita_db_por_id:", e)
        return None


def cancelar_cita_db_por_id(id_cita):
    try:
        supabase.table("citas").update({"servicio": "CITA CANCELADA"}).eq("id", id_cita).execute()
        return True
    except Exception as e:
        print("Error cancelar_cita_db_por_id:", e)
        return False


def marcar_atendida_db_por_id(id_cita):
    try:
        supabase.table("citas").update({"servicio": "CITA ATENDIDA"}).eq("id", id_cita).execute()
        return True
    except Exception as e:
        print("Error marcar_atendida_db_por_id:", e)
        return False


# ==========================================================
# WRAPPERS
# ==========================================================
def leer_citas():
    return leer_citas_db() if USAR_SUPABASE else leer_citas_txt()


def guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        ok = guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
        if not ok:
            guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)
    else:
        guardar_cita_txt(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)


def buscar_cita_por_id(id_cita):
    if USAR_SUPABASE:
        c = buscar_cita_db_por_id(id_cita)
        if c:
            return c
    return buscar_cita_txt_por_id(id_cita)


def cancelar_cita_por_id(id_cita):
    if USAR_SUPABASE:
        ok = cancelar_cita_db_por_id(id_cita)
        if ok:
            return True
    cancelar_cita_txt_por_id(id_cita)
    return True


def marcar_atendida_por_id(id_cita):
    if USAR_SUPABASE:
        ok = marcar_atendida_db_por_id(id_cita)
        if ok:
            return True
    marcar_atendida_txt_por_id(id_cita)
    return True


# =========================
# WEBHOOK (Meta)
# =========================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN:
            return challenge
        return "Token incorrecto", 403

    data = request.get_json()

    try:
        value = data["entry"][0]["changes"][0]["value"]

        # Ignorar eventos que NO son mensajes
        if "messages" not in value:
            return "ok", 200

        msg = value["messages"][0]
        numero = msg.get("from")
        msg_id = msg.get("id")

        # limpiar viejos
        ahora = time.time()
        for k, t in list(PROCESADOS.items()):
            if ahora - t > TTL_MSG:
                PROCESADOS.pop(k, None)

        if msg_id and msg_id in PROCESADOS:
            return "ok", 200
        if msg_id:
            PROCESADOS[msg_id] = ahora

        link = f"{DOMINIO}/?cliente_id={numero}"

        mensaje = f"""Hola 👋 Bienvenido a Barbería {NOMBRE_BARBERO} 💈

Para agendar tu cita entra aquí:
{link}

(Guarda este link para cancelar luego)
"""
        enviar_whatsapp(numero, mensaje)

    except Exception as e:
        print("Error webhook:", e)

    return "ok", 200


# =========================
# RUTAS APP
# =========================
@app.route("/", methods=["GET", "POST"])
def index():
    cliente_id_url = request.args.get("cliente_id")
    cliente_id_cookie = request.cookies.get("cliente_id")

    if cliente_id_url:
        cliente_id = str(cliente_id_url).strip()
    elif cliente_id_cookie:
        cliente_id = str(cliente_id_cookie).strip()
    else:
        cliente_id = str(uuid.uuid4())

    citas_todas = leer_citas()

    # cliente solo ve sus citas
    citas_cliente = [c for c in citas_todas if str(c.get("cliente_id", "")) == str(cliente_id)]

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()

        barbero_raw = request.form.get("barbero", "").strip()
        servicio = request.form.get("servicio", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        cliente_id_form = request.form.get("cliente_id")
        if cliente_id_form:
            cliente_id = str(cliente_id_form).strip()

        barbero = normalizar_barbero(barbero_raw)
        precio = str(servicios.get(servicio, 0))

        conflict = any(
            normalizar_barbero(c.get("barbero", "")) == barbero
            and str(c.get("fecha", "")) == fecha
            and str(c.get("hora", "")) == hora
            and c.get("servicio") != "CITA CANCELADA"
            for c in citas_todas
        )

        if conflict:
            flash("La hora seleccionada ya está ocupada. Por favor elige otra.")
            resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
            resp.set_cookie("cliente_id", cliente_id, max_age=60 * 60 * 24 * 365)
            return resp

        id_cita = str(uuid.uuid4())
        guardar_cita(id_cita, cliente, cliente_id, barbero, servicio, precio, fecha, hora)

        msg_barbero = f"""💈 Nueva cita agendada

Cliente: {cliente}
Barbero: {barbero}
Servicio: {servicio}
Fecha: {fecha}
Hora: {hora}
Precio: ₡{precio}
"""
        enviar_whatsapp(NUMERO_BARBERO, msg_barbero)

        if es_numero_whatsapp(cliente_id):
            link = f"{DOMINIO}/?cliente_id={cliente_id}"
            msg_cliente = f"""✅ Cita confirmada en Barbería {NOMBRE_BARBERO} 💈

Cliente: {cliente}
Barbero: {barbero}
Servicio: {servicio}
Fecha: {fecha}
Hora: {hora}
Total: ₡{precio}

Para cancelar: entra a este link:
{link}
"""
            enviar_whatsapp(cliente_id, msg_cliente)

        flash("Cita agendada exitosamente")
        resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
        resp.set_cookie("cliente_id", cliente_id, max_age=60 * 60 * 24 * 365)
        return resp

    resp = make_response(render_template(
        "index.html",
        servicios=servicios,
        citas=citas_cliente,
        cliente_id=cliente_id,
        numero_barbero=NUMERO_BARBERO,
        nombre_barbero=NOMBRE_BARBERO
    ))
    resp.set_cookie("cliente_id", cliente_id, max_age=60 * 60 * 24 * 365)
    return resp


@app.route("/cancelar", methods=["POST"])
def cancelar():
    id_cita = request.form.get("id")
    if not id_cita:
        flash("Error: no se recibió el ID de la cita")
        return redirect(url_for("index"))

    cita = buscar_cita_por_id(id_cita)
    if not cita:
        flash("No se encontró la cita")
        return redirect(url_for("index"))

    cancelar_cita_por_id(id_cita)

    cliente = cita.get("cliente", "")
    cliente_id = str(cita.get("cliente_id", ""))
    barbero = cita.get("barbero", "")
    fecha = cita.get("fecha", "")
    hora = cita.get("hora", "")

    msg_barbero = f"""❌ Cita CANCELADA

Cliente: {cliente}
Barbero: {barbero}
Fecha: {fecha}
Hora: {hora}
"""
    enviar_whatsapp(NUMERO_BARBERO, msg_barbero)

    if es_numero_whatsapp(cliente_id):
        msg_cliente = f"""❌ Tu cita en Barbería {NOMBRE_BARBERO} fue cancelada

Barbero: {barbero}
Fecha: {fecha}
Hora: {hora}

Si deseas agendar de nuevo, entra al link.
"""
        enviar_whatsapp(cliente_id, msg_cliente)

    flash("Cita cancelada correctamente")
    resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
    resp.set_cookie("cliente_id", cliente_id, max_age=60 * 60 * 24 * 365)
    return resp


# ✅ Marcar atendida (SOLO BARBERO)
@app.route("/atendida", methods=["POST"])
def atendida():
    if not barbero_autenticado():
        return redirect(url_for("barbero"))

    id_cita = request.form.get("id")
    if not id_cita:
        return redirect(url_for("barbero"))

    marcar_atendida_por_id(id_cita)
    return redirect(url_for("barbero"))


# ✅ Panel del barbero protegido por clave (cookie)
@app.route("/barbero", methods=["GET"])
def barbero():
    clave = request.args.get("clave")

    # Si ya autenticó antes, entra directo
    if barbero_autenticado():
        return _render_panel_barbero()

    # Si está metiendo la clave por primera vez
    if clave == CLAVE_BARBERO:
        resp = make_response(_render_panel_barbero())
        resp.set_cookie("clave_barbero", CLAVE_BARBERO, max_age=60 * 60 * 24 * 7)  # 7 días
        return resp

    # Formulario de clave (cuando no está autenticado)
    return """
    <div style='font-family:Arial;max-width:420px;margin:40px auto;padding:20px;border:1px solid #ddd;border-radius:12px;'>
      <h2>🔒 Panel del barbero</h2>
      <form method='GET'>
        <input name='clave' placeholder='Ingrese clave' style='padding:10px;font-size:16px;width:100%;margin:10px 0;'>
        <button type='submit' style='padding:10px;width:100%;font-size:16px;'>Entrar</button>
      </form>
    </div>
    """


def _render_panel_barbero():
    citas = leer_citas()

    solo = request.args.get("solo", "hoy")          # hoy | manana | todas
    estado = request.args.get("estado", "activas")  # activas | atendidas | canceladas | todas
    q = (request.args.get("q") or "").strip().lower()

    hoy = date.today().strftime("%Y-%m-%d")
    manana = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    # filtro por fecha
    if solo == "hoy":
        citas = [c for c in citas if str(c.get("fecha")) == hoy]
    elif solo == "manana":
        citas = [c for c in citas if str(c.get("fecha")) == manana]
    # todas -> no filtra

    # filtro por estado
    if estado == "activas":
        citas = [c for c in citas if c.get("servicio") not in ["CITA CANCELADA", "CITA ATENDIDA"]]
    elif estado == "canceladas":
        citas = [c for c in citas if c.get("servicio") == "CITA CANCELADA"]
    elif estado == "atendidas":
        citas = [c for c in citas if c.get("servicio") == "CITA ATENDIDA"]
    # todas -> no filtra

    # búsqueda
    if q:
        citas = [
            c for c in citas
            if q in str(c.get("cliente", "")).lower()
            or q in str(c.get("servicio", "")).lower()
        ]

    # ordenar
    citas.sort(key=lambda c: (str(c.get("fecha", "")), str(c.get("hora", ""))))

    fecha_actual = hoy
    return render_template("barbero.html", citas=citas, fecha_actual=fecha_actual)


@app.route("/citas_json")
def citas_json():
    citas = leer_citas()
    return jsonify({"citas": citas})


@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero = request.args.get("barbero")

    if not fecha or not barbero:
        return jsonify([])

    barbero_norm = normalizar_barbero(barbero)

    citas = leer_citas()
    ocupadas = [
        c.get("hora") for c in citas
        if normalizar_barbero(c.get("barbero", "")) == barbero_norm
        and str(c.get("fecha", "")) == str(fecha)
        and c.get("servicio") != "CITA CANCELADA"
    ]

    disponibles = [h for h in HORAS_BASE if h not in ocupadas]
    return jsonify(disponibles)


if __name__ == "__main__":
    app.run(debug=True)








