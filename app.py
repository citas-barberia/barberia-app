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
#  MODO RESPALDO: TXT
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
                    "id": None,
                    "cliente": c[0],
                    "cliente_id": "TXT",
                    "barbero": c[1],
                    "servicio": c[2],
                    "precio": c[3],
                    "fecha": c[4],
                    "hora": c[5],
                })
    except FileNotFoundError:
        pass
    return citas

def guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
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
#  SUPABASE (SQL): usa tu tabla public.citas (la real)
#  Columnas: id, cliente, cliente_id, barbero, servicio, precio, fecha, hora, created_at
# ==========================================================
def leer_citas_db():
    try:
        # Ordenar por created_at si existe (tu tabla lo tiene)
        res = supabase.table("citas").select("*").order("created_at", desc=True).execute()
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
                "fecha": str(r.get("fecha", "")),  # viene como 'YYYY-MM-DD'
                "hora": str(r.get("hora", "")),
            })
        return citas
    except Exception as e:
        print("Error leer_citas_db:", e)
        return []

def guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    try:
        supabase.table("citas").insert({
            # id NO se manda: tu tabla lo genera sola (identity)
            "cliente": cliente,
            "cliente_id": cliente_id,
            "barbero": barbero,
            "servicio": servicio,
            "precio": int(precio),
            "fecha": fecha,   # 'YYYY-MM-DD' -> Postgres lo castea a date
            "hora": hora
        }).execute()
        return True
    except Exception as e:
        print("Error guardar_cita_db:", e)
        return False

def cancelar_cita_db(cliente, barbero, fecha, hora):
    try:
        # Marcamos como cancelada (igual que tu txt)
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

def guardar_cita(cliente, cliente_id, barbero, servicio, precio, fecha, hora):
    if USAR_SUPABASE:
        ok = guardar_cita_db(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
        if not ok:
            # Si falla DB, no rompe: guarda en TXT
            guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
    else:
        guardar_cita_txt(cliente, cliente_id, barbero, servicio, precio, fecha, hora)

def cancelar_cita(cliente, barbero, fecha, hora):
    if USAR_SUPABASE:
        ok = cancelar_cita_db(cliente, barbero, fecha, hora)
        if not ok:
            cancelar_cita_txt(cliente, barbero, fecha, hora)
    else:
        cancelar_cita_txt(cliente, barbero, fecha, hora)


# ==========================================================
#  RUTAS
# ==========================================================

# ===== Ruta del cliente =====
@app.route("/", methods=["GET", "POST"])
def index():
    # Si viene cliente_id por URL, lo mantenemos.
    # Si no, generamos uno (esto no rompe tu HTML).
    cliente_id = request.args.get("cliente_id")
    if not cliente_id:
        cliente_id = str(uuid.uuid4())

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
            guardar_cita(cliente, cliente_id, barbero, servicio, precio, fecha, hora)
            flash("Cita agendada exitosamente")

        # Volvemos a / manteniendo cliente_id en la URL
        return redirect(url_for("index", cliente_id=cliente_id))

    # Render sin romper tu index.html
    return render_template("index.html", servicios=servicios, citas=citas)


# ===== Ruta de cancelar cita =====
@app.route("/cancelar", methods=["POST"])
def cancelar_route():
    # OJO: esto depende de tu index.html.
    # Si tu formulario manda "cliente/barbero/fecha/hora", funciona.
    # Si mandas "id", lo podemos adaptar luego (sin romper).
    cliente = request.form.get("cliente")
    barbero = request.form.get("barbero")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")

    if not (cliente and barbero and fecha and hora):
        flash("Error: faltan datos para cancelar la cita.")
        return redirect(url_for("index"))

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


