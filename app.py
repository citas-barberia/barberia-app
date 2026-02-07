from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from datetime import date
import os
import uuid

app = Flask(__name__)
app.secret_key = "secret_key"  # Necesario para mensajes flash

# ===== Servicios con precios =====
servicios = {
    "Corte de cabello": 5000,
    "Corte + barba": 7000,
    "Solo barba": 5000,
    "Solo cejas": 2000
}

# ===== Horas base =====
HORAS_BASE = ["09:00am","10:00am","11:00am","12:00md","1:00pm","2:00pm","3:00pm","4:00pm","5:00pm"]

# ===== Supabase config (SQL) =====
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
#  MODO RESPALDO: TXT (igual que tu versión anterior)
# ==========================================================
def leer_citas_txt():
    citas = []
    try:
        with open("citas.txt", "r", encoding="utf-8") as f:
            for linea in f:
                if linea.strip() == "":
                    continue
                c = linea.strip().split("|")
                if len(c) < 6:
                    continue
                citas.append({
                    "cliente": c[0],
                    "barbero": c[1],
                    "servicio": c[2],
                    "precio": c[3],
                    "fecha": c[4],
                    "hora": c[5],
                })
    except FileNotFoundError:
        pass
    return citas

def guardar_cita_txt(cliente, barbero, servicio, precio, fecha, hora):
    with open("citas.txt", "a", encoding="utf-8") as f:
        f.write(f"{cliente}|{barbero}|{servicio}|{precio}|{fecha}|{hora}\n")

def cancelar_cita_txt(cliente, barbero, fecha, hora):
    citas = leer_citas_txt()
    with open("citas.txt", "w", encoding="utf-8") as f:
        for c in citas:
            if c["cliente"] == cliente and c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora:
                f.write(f"{c['cliente']}|{c['barbero']}|CITA CANCELADA|{c['precio']}|{c['fecha']}|{c['hora']}\n")
            else:
                f.write(f"{c['cliente']}|{c['barbero']}|{c['servicio']}|{c['precio']}|{c['fecha']}|{c['hora']}\n")


# ==========================================================
#  SUPABASE (SQL): mismas funciones pero usando DB
#  Tabla esperada: public.citas
#  Columnas recomendadas:
#    id (text/uuid, PK), cliente (text), barbero (text),
#    servicio (text), precio (int), fecha (text o date),
#    hora (text), created_at (timestamptz opcional)
# ==========================================================
def leer_citas_db():
    # Trae todas las citas (orden opcional por created_at si existe)
    try:
        res = supabase.table("citas").select("*").execute()
        data = res.data if res and res.data else []
        # Asegura las llaves que usa tu HTML
        citas = []
        for r in data:
            citas.append({
                "id": r.get("id"),
                "cliente": r.get("cliente", ""),
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

def guardar_cita_db(cliente, barbero, servicio, precio, fecha, hora):
    try:
        supabase.table("citas").insert({
            "id": str(uuid.uuid4()),
            "cliente": cliente,
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

def cancelar_cita_db(cliente, barbero, fecha, hora):
    # No borramos: marcamos como CITA CANCELADA (igual que tu TXT)
    try:
        supabase.table("citas").update({
            "servicio": "CITA CANCELADA"
        }).match({
            "cliente": cliente,
            "barbero": barbero,
            "fecha": fecha,
            "hora": hora
        }).execute()
        return True
    except Exception as e:
        print("Error cancelar_cita_db:", e)
        return False


# ==========================================================
#  Wrappers (elige DB o TXT automáticamente)
# ==========================================================
def leer_citas():
    return leer_citas_db() if USAR_SUPABASE else leer_citas_txt()

def guardar_cita(cliente, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        ok = guardar_cita_db(cliente, barbero, servicio, precio, fecha, hora)
        if not ok:
            # Si falla DB, no rompe: guarda en TXT
            guardar_cita_txt(cliente, barbero, servicio, precio, fecha, hora)
    else:
        guardar_cita_txt(cliente, barbero, servicio, precio, fecha, hora)

def cancelar_cita(cliente, barbero, fecha, hora):
    if USAR_SUPABASE:
        ok = cancelar_cita_db(cliente, barbero, fecha, hora)
        if not ok:
            cancelar_cita_txt(cliente, barbero, fecha, hora)
    else:
        cancelar_cita_txt(cliente, barbero, fecha, hora)


# ===== Ruta del cliente =====
@app.route("/", methods=["GET", "POST"])
def index():
    citas = leer_citas()

    if request.method == "POST":
        cliente = request.form["cliente"]
        barbero = request.form["barbero"]
        servicio = request.form["servicio"]
        precio = str(servicios.get(servicio, 0))
        fecha = request.form["fecha"]
        hora = request.form["hora"]

        # Verificar si la hora ya está ocupada para el mismo barbero y mismo día
        conflict = any(
            c["barbero"] == barbero and c["fecha"] == fecha and c["hora"] == hora and c["servicio"] != "CITA CANCELADA"
            for c in citas
        )

        if conflict:
            flash("La hora seleccionada ya está ocupada. Por favor elige otra.")
        else:
            guardar_cita(cliente, barbero, servicio, precio, fecha, hora)
            flash("Cita agendada exitosamente")

        return redirect(url_for("index"))

    return render_template("index.html", servicios=servicios, citas=citas)


# ===== Ruta de cancelar cita =====
@app.route("/cancelar", methods=["POST"])
def cancelar():
    cliente = request.form["cliente"]
    barbero = request.form["barbero"]
    fecha = request.form["fecha"]
    hora = request.form["hora"]

    cancelar_cita(cliente, barbero, fecha, hora)
    flash("Cita cancelada")
    return redirect(url_for("index"))


# ===== Ruta del barbero =====
@app.route("/barbero")
def barbero():
    citas = leer_citas()
    fecha_actual = date.today().strftime("%Y-%m-%d")
    return render_template("barbero.html", citas=citas, fecha_actual=fecha_actual)


# ===== Ruta JSON para actualizar las citas del barbero =====
@app.route("/citas_json")
def citas_json():
    citas = leer_citas()
    return jsonify({"citas": citas})


# ===== Ruta para horas disponibles =====
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


# ===== Arrancar servidor =====
if __name__ == "__main__":
    app.run(debug=True)

