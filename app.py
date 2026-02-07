from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from datetime import date
import os
import uuid
import requests

app = Flask(__name__)
app.secret_key = "secret_key"  # Necesario para mensajes flash

# =========================
# CONFIG WHATSAPP (Meta)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "barberia123")  # para /webhook GET
NUMERO_BARBERO = os.getenv("NUMERO_BARBERO", "50672314147")  # a quién le llega todo
DOMINIO = os.getenv("DOMINIO", "https://barberia-app-1.onrender.com")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")


def enviar_whatsapp(to_numero: str, mensaje: str):
    """Envía un WhatsApp por Cloud API."""
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
    """True si parece un número tipo 506xxxxxxx (solo dígitos)."""
    if not valor:
        return False
    s = str(valor).strip()
    return s.isdigit() and len(s) >= 8


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
#  RESPALDO TXT
#  Formato: cliente|cliente_id|barbero|servicio|precio|fecha|hora
# ==========================================================
def leer_citas_txt():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if not linea.strip():
                    continue
                c = linea.strip().split("|")
                if len(c) != 7:
                    continue

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
    except FileNotFoundError:
        pass
    return citas


def guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{cliente}|{cliente_id}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")


def cancelar_cita_txt(id_cita, cliente, cliente_id, barbero, fecha, hora):
    """Marca como CITA CANCELADA, no borra."""
    citas = leer_citas_txt()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            if (
                c["cliente"] == cliente and
                c["cliente_id"] == cliente_id and
                c["barbero"] == barbero and
                c["fecha"] == fecha and
                c["hora"] == hora and
                c["servicio"] != "CITA CANCELADA"
            ):
                f.write(f"{c['cliente']}|{c['cliente_id']}|{c['barbero']}|CITA CANCELADA|{c['precio']}|{c['fecha']}|{c['hora']}\n")
            else:
                f.write(f"{c['cliente']}|{c['cliente_id']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")


# ==========================================================
#  SUPABASE DB: tabla public.citas
#  columnas esperadas según tu screenshot:
#  id (bigint identity), cliente text, cliente_id text, barbero text,
#  servicio text, precio bigint, fecha date, hora text, created_at timestamptz
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
            "fecha": fecha,     # supabase acepta string "YYYY-MM-DD" para date
            "hora": hora
        }).execute()
        return True
    except Exception as e:
        print("Error guardar_cita_db:", e)
        return False


def cancelar_cita_db(id_cita=None, cliente=None, cliente_id=None, barbero=None, fecha=None, hora=None):
    """Marca como CITA CANCELADA. Preferimos match por id si existe."""
    try:
        q = supabase.table("citas").update({"servicio": "CITA CANCELADA"})

        if id_cita is not None:
            q = q.eq("id", id_cita)
        else:
            q = q.match({
                "cliente": cliente,
                "cliente_id": str(cliente_id),
                "barbero": barbero,
                "fecha": fecha,
                "hora": hora,
            })

        q.execute()
        return True
    except Exception as e:
        print("Error cancelar_cita_db:", e)
        return False


# ==========================================================
#  WRAPPERS: elige DB o TXT automáticamente
# ==========================================================
def leer_citas():
    return leer_citas_db() if USAR_SUPABASE else leer_citas_txt()


def guardar_cita(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        ok = guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
        if not ok:
            guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
    else:
        guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora)


def cancelar_cita(id_cita, cliente, cliente_id, barbero, fecha, hora):
    if USAR_SUPABASE:
        ok = cancelar_cita_db(id_cita=id_cita, cliente=cliente, cliente_id=cliente_id, barbero=barbero, fecha=fecha, hora=hora)
        if not ok:
            cancelar_cita_txt(id_cita, cliente, cliente_id, barbero, fecha, hora)
    else:
        cancelar_cita_txt(id_cita, cliente, cliente_id, barbero, fecha, hora)


# =========================
# WEBHOOK (opcional pero recomendado)
# =========================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Verificación Meta
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN:
            return challenge
        return "Token incorrecto", 403

    # Mensaje entrante
    data = request.get_json()
    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return "ok", 200

        numero = value["messages"][0]["from"]
        link = f"{DOMINIO}/?cliente_id={numero}"

        mensaje = f"""Hola 👋 Bienvenido a Barbería José 💈

Para agendar tu cita entra aquí:
{link}
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
    # Si vienen desde WhatsApp: /?cliente_id=506xxxx
    cliente_id = request.args.get("cliente_id")
    if not cliente_id:
        # Si entra normal desde navegador, igual funciona:
        cliente_id = str(uuid.uuid4())

    citas = leer_citas()

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        barbero = request.form.get("barbero", "").strip()
        servicio = request.form.get("servicio", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        # cliente_id puede venir como hidden input
        cliente_id_form = request.form.get("cliente_id")
        if cliente_id_form:
            cliente_id = cliente_id_form.strip()

        precio = str(servicios.get(servicio, 0))

        # Conflicto: misma fecha+hora+barbero, y no cancelada
        conflict = any(
            c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora and c["servicio"] != "CITA CANCELADA"
            for c in citas
        )

        if conflict:
            flash("La hora seleccionada ya está ocupada. Por favor elige otra.")
            return redirect(url_for("index", cliente_id=cliente_id))

        # Guardar
        guardar_cita(cliente, cliente_id, barbero, servicio, precio, fecha, hora)

        # WhatsApp al barbero
        msg_barbero = f"""💈 Nueva cita agendada

Cliente: {cliente}
Barbero: {barbero}
Servicio: {servicio}
Fecha: {fecha}
Hora: {hora}
Precio: ₡{precio}
"""
        enviar_whatsapp(NUMERO_BARBERO, msg_barbero)

        # WhatsApp al cliente (si venía desde WA con número real)
        if es_numero_whatsapp(cliente_id):
            msg_cliente = f"""✅ Cita confirmada 💈

Cliente: {cliente}
Barbero: {barbero}
Servicio: {servicio}
Fecha: {fecha}
Hora: {hora}
Total: ₡{precio}

Si necesitas cancelar, entra al link donde agendaste.
"""
            enviar_whatsapp(cliente_id, msg_cliente)

        flash("Cita agendada exitosamente")
        return redirect(url_for("index", cliente_id=cliente_id))

    return render_template("index.html", servicios=servicios, citas=citas, cliente_id=cliente_id)


@app.route("/cancelar", methods=["POST"])
def cancelar():
    # Para cancelar sin errores, recibimos todo lo necesario
    id_cita = request.form.get("id")  # puede venir vacío
    cliente = request.form.get("cliente", "").strip()
    cliente_id = request.form.get("cliente_id", "").strip()
    barbero = request.form.get("barbero", "").strip()
    fecha = request.form.get("fecha", "").strip()
    hora = request.form.get("hora", "").strip()

    cancelar_cita(id_cita, cliente, cliente_id, barbero, fecha, hora)

    # WhatsApp barbero
    msg_barbero = f"""❌ Cita CANCELADA

Cliente: {cliente}
Barbero: {barbero}
Fecha: {fecha}
Hora: {hora}
"""
    enviar_whatsapp(NUMERO_BARBERO, msg_barbero)

    # WhatsApp cliente si es número real
    if es_numero_whatsapp(cliente_id):
        msg_cliente = f"""❌ Tu cita fue cancelada

Barbero: {barbero}
Fecha: {fecha}
Hora: {hora}

Si deseas agendar de nuevo, entra al link.
"""
        enviar_whatsapp(cliente_id, msg_cliente)

    flash("Cita cancelada")
    return redirect(url_for("index", cliente_id=cliente_id if cliente_id else None))


@app.route("/barbero")
def barbero():
    citas = leer_citas()
    fecha_actual = date.today().strftime("%Y-%m-%d")
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

    citas = leer_citas()
    ocupadas = [
        c["hora"] for c in citas
        if c["barbero"] == barbero and c["fecha"] == fecha and c["servicio"] != "CITA CANCELADA"
    ]
    disponibles = [h for h in HORAS_BASE if h not in ocupadas]
    return jsonify(disponibles)


if __name__ == "__main__":
    app.run(debug=True)



