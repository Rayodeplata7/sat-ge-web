import os
import csv
import json
import math
import time
import sqlite3
import threading
import socket
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, send_from_directory
import qrcode
import io
import base64

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sat_geo_data.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)

ALLOWED_ORIGINS = {
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "https://rayodeplata7.github.io",
}

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@app.route("/presentacion")
def serve_presentation():
    pres_path = os.path.join(os.path.dirname(BASE_DIR), "presentacion_interactiva_sat_geo.html")
    if os.path.exists(pres_path):
        with open(pres_path, "r", encoding="utf-8") as f:
            return f.read()
    return "Archivo de presentacion no encontrado", 404

# Estado global del sistema en tiempo real (hardware-first: sin valores inventados)
state = {
    "hum": 0.0,
    "force": 0.0,
    "disp": 0.0,
    "vib": 0.0,
    "tilt": 0.0,
    "moment": 0.0,
    "raw_fsr": 0,
    "raw_ir": 0,
    "raw_soil": 0,
    "acc_x": 0,
    "acc_y": 0,
    "acc_z": 0,
    "fs": 0.0,
    "status": "DESCONECTADO",
    "ttf": "--",
    "serial_connected": False,
    "port": "SIN HARDWARE",
    "last_update": datetime.now().strftime("%H:%M:%S.%f")[:-3],
    "cable_fault": False,
    "sim_storm": False,
    "momento": "M1_REPOSO",
    "tare_requested": False
}

state_lock = threading.Lock()

# -------------------------------------------------------------
# Base de Datos SQLite para Historial Completo
# -------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    c.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            hum REAL,
            force REAL,
            disp REAL,
            vib REAL,
            fs REAL,
            status TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sensor_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            momento TEXT,
            raw_fsr INTEGER,
            force_n REAL,
            raw_ir INTEGER,
            disp_mm REAL,
            raw_soil INTEGER,
            hum_pct REAL,
            acc_x INTEGER,
            acc_y INTEGER,
            acc_z INTEGER,
            tilt_deg REAL,
            vib_g REAL,
            fs REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_reading(hum, force, disp, vib, fs, status, snap=None):
    if not snap or (not snap.get("serial_connected") and not snap.get("sim_storm")):
        return
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        c = conn.cursor()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        c.execute('''
            INSERT INTO telemetry (timestamp, hum, force, disp, vib, fs, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (ts[:19], hum, force, disp, vib, fs, status))
        if snap and snap.get("serial_connected"):
            c.execute('''
                INSERT INTO sensor_samples (
                    timestamp, momento, raw_fsr, force_n, raw_ir, disp_mm,
                    raw_soil, hum_pct, acc_x, acc_y, acc_z, tilt_deg, vib_g, fs, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ts, snap.get("momento", "M1_REPOSO"),
                int(snap.get("raw_fsr", 0)), float(force),
                int(snap.get("raw_ir", 0)), float(disp),
                int(snap.get("raw_soil", 0)), float(hum),
                int(snap.get("acc_x", 0)), int(snap.get("acc_y", 0)), int(snap.get("acc_z", 0)),
                float(snap.get("tilt", 0.0)), float(vib), float(fs), str(status)
            ))
        conn.commit()
    except Exception as e:
        print(f"Error saving to DB: {e}")
    finally:
        if conn is not None:
            conn.close()

# -------------------------------------------------------------
# Algoritmo de Predicción y Factor de Seguridad (FS)
# -------------------------------------------------------------
def compute_geotech(hum, force, disp, vib, fault):
    if fault:
        return 0.0, "DESCONECTADO", "ERROR HARDWARE"
    
    # Carga de riesgo combinada de los 4 dominios físicos
    # hum: 0 a 100% | force: 0 a 4.4N | disp: 0 a 25mm | vib: 0 a 2g
    risk = (hum / 100.0) * 0.60 + (force / 4.4) * 0.70 + (disp / 25.0) * 0.55 + (vib / 2.0) * 0.35
    fs = max(0.40, round(2.50 - risk * 1.45, 2))
    
    if fs < 1.05:
        status = "COLAPSO"
        secs = max(5, int(fs * 22))
        ttf = f"00:{secs:02d} seg"
    elif fs < 1.50:
        status = "PRECAUCION"
        ttf = "~03:15 min"
    else:
        status = "SEGURO"
        ttf = "∞ (ESTABLE)"
        
    return fs, status, ttf

# -------------------------------------------------------------
# Lector Serial de la STM32F407VG en Segundo Plano
# -------------------------------------------------------------
def serial_worker():
    global state
    db_counter = 0
    sim_t = 0

    while True:
        ser = None
        target_port = None
        # Auto-Tara de 10 muestras + Filtro EMA (paridad exacta con Web y Android)
        has_base = False
        tare_n = 0
        sum_fsr = sum_ir = sum_ax = sum_ay = sum_az = 0.0
        base_fsr = 65.0
        base_ir = 4095.0
        base_ax = 0.0
        base_ay = 0.0
        base_az = 256.0
        ema_fsr = None
        prev_ax = prev_ay = 0.0
        prev_az = 256.0
        vib_peak = 0.0
        last_raw_f = 65.0
        last_raw_ir = 4095.0
        last_ax = 0.0
        last_ay = 0.0
        last_az = 256.0
        
        if SERIAL_AVAILABLE:
            all_ports = list(serial.tools.list_ports.comports())
            # Priorizar puentes USB-UART reales (CP210x, CH340, FTDI) y evitar Bluetooth / COM1
            usb_candidates = []
            for p in all_ports:
                desc = f"{p.description or ''} {p.hwid or ''}".lower()
                if p.device == "COM1" or "bluetooth" in desc or "bthenum" in desc:
                    continue
                if any(k in desc for k in ("cp210", "silicon labs", "ch340", "ftdi", "usb")):
                    usb_candidates.insert(0, p.device)
                else:
                    usb_candidates.append(p.device)
            if usb_candidates:
                target_port = usb_candidates[0]
        
        if target_port:
            try:
                ser = serial.Serial(target_port, 115200, timeout=1.0)
                print(f"[ESP32] Conectado en puerto {target_port}!")
                with state_lock:
                    state["serial_connected"] = True
                    state["port"] = target_port
            except Exception as e:
                ser = None
        
        # Loop de lectura o simulación (con re-escaneo hot-plug cada 2s si no hay puerto abierto)
        no_port_ticks = 0
        while True:
            read_success = False
            line = ""
            if ser is None:
                no_port_ticks += 1
                if no_port_ticks >= 10:
                    break
            if ser and ser.is_open:
                try:
                    while ser.in_waiting > 0:
                        candidate = ser.readline().decode('utf-8', errors='ignore').strip()
                        if candidate.startswith("@") and candidate.endswith(";"):
                            line = candidate
                    if not line:
                        candidate = ser.readline().decode('utf-8', errors='ignore').strip()
                        if candidate.startswith("@") and candidate.endswith(";"):
                            line = candidate
                    if line:
                        clean = line[1:-1].strip()
                        if clean.startswith(","):
                            clean = clean[1:]
                        parts = clean.split(",")
                        if len(parts) >= 9 and parts[0] == "00" and parts[1] == "6":
                            # Protocolo SAT-GEO 6 Canales ESP32: @,00,6,raw_fsr,raw_ir,raw_soil,acc_x,acc_y,acc_z,xor;
                            payload_str = ",".join(parts[:8])
                            calc_xor = 0
                            for ch in payload_str:
                                calc_xor ^= ord(ch)
                            try:
                                rx_xor = int(parts[8], 16)
                            except ValueError:
                                rx_xor = -1
                            if calc_xor == rx_xor:
                                raw_f = int(float(parts[2]))     # FSR-406 (GPIO34)
                                raw_ir = int(float(parts[3]))    # IR P/N 1102 (GPIO35)
                                raw_soil = int(float(parts[4]))  # Sonda Suelo (GPIO32)
                                acc_x = int(float(parts[5]))     # ADXL345 X
                                acc_y = int(float(parts[6]))     # ADXL345 Y
                                acc_z = int(float(parts[7]))     # ADXL345 Z

                                with state_lock:
                                    if state.get("tare_requested"):
                                        state["tare_requested"] = False
                                        has_base = True
                                        tare_n = 10
                                        base_fsr = ema_fsr if ema_fsr is not None else float(raw_f)
                                        base_ir = float(raw_ir)
                                        base_ax, base_ay, base_az = float(acc_x), float(acc_y), float(acc_z)
                                        vib_peak = 0.0

                                ema_fsr = float(raw_f) if ema_fsr is None else (ema_fsr * 0.65 + raw_f * 0.35)
                                if not has_base:
                                    tare_n += 1
                                    sum_fsr += ema_fsr
                                    sum_ir += float(raw_ir)
                                    sum_ax += float(acc_x)
                                    sum_ay += float(acc_y)
                                    sum_az += float(acc_z)
                                    base_fsr = sum_fsr / tare_n
                                    base_ir = sum_ir / tare_n
                                    base_ax = sum_ax / tare_n
                                    base_ay = sum_ay / tare_n
                                    base_az = sum_az / tare_n
                                    prev_ax, prev_ay, prev_az = float(acc_x), float(acc_y), float(acc_z)
                                    if tare_n >= 10:
                                        has_base = True

                                # 1) FSR-406 ultra-sensible (banda muerta minima 14 ADC sobre piso real de ruido)
                                eff_fsr = max(0.0, abs(ema_fsr - base_fsr) - 14.0)
                                f = round(min(4.4, eff_fsr * 0.025), 2)

                                # 2) Sonda Humedad Suelo ultra-sensible (GPIO32: 4092 seco -> saturado)
                                h = round(max(8.0, min(100.0, 8.0 + ((4092.0 - raw_soil) / 1500.0) * 92.0)), 1)

                                # 3) Sensor IR P/N 1102 ultra-sensible (piso ruido = 0, banda muerta 4 ADC)
                                delta_ir = abs(raw_ir - base_ir)
                                d = round(min(50.0, max(0.0, (delta_ir - 4.0) * 0.045)), 2)

                                # 4) ADXL345 ultra-sensible: angulo 3D relativo (0.25°) + micro-vibracion (0.015g)
                                mag1 = math.sqrt(acc_x * acc_x + acc_y * acc_y + acc_z * acc_z)
                                mag2 = math.sqrt(base_ax * base_ax + base_ay * base_ay + base_az * base_az)
                                if mag1 > 10.0 and mag2 > 10.0:
                                    cos_a = max(-1.0, min(1.0, (acc_x * base_ax + acc_y * base_ay + acc_z * base_az) / (mag1 * mag2)))
                                    raw_tilt = math.degrees(math.acos(cos_a))
                                else:
                                    raw_tilt = 0.0
                                tilt_deg = round((raw_tilt - 0.25) * 2.2, 2) if raw_tilt > 0.25 else 0.0

                                dv = math.sqrt((acc_x - prev_ax) ** 2 + (acc_y - prev_ay) ** 2 + (acc_z - prev_az) ** 2) / 256.0
                                prev_ax, prev_ay, prev_az = float(acc_x), float(acc_y), float(acc_z)
                                vib_peak = max(vib_peak * 0.84, dv)
                                v = round((vib_peak - 0.015) * 3.5, 3) if vib_peak > 0.015 else 0.0

                                last_raw_f, last_raw_ir = float(raw_f), float(raw_ir)
                                last_ax, last_ay, last_az = float(acc_x), float(acc_y), float(acc_z)
                                read_success = True
                        elif len(parts) >= 6 and parts[0] == "00" and parts[1] == "4":
                            # Protocolo SAT-GEO 4 Canales
                            raw_f = float(parts[2])
                            raw_h = float(parts[3])
                            raw_ir = float(parts[4])
                            raw_acc = float(parts[5])
                            f = round((raw_f / 4095.0) * 4.4, 2)
                            h = round(max(0.0, min(100.0, ((3700.0 - raw_h) / 2800.0) * 100.0)), 1)
                            d = round((raw_ir / 4095.0) * 30.0, 1)
                            v = round(max(0.02, raw_acc / 1000.0), 2)
                            read_success = True
                        elif len(parts) >= 4 and parts[0] == "00":
                            # Protocolo STM32 del laboratorio: @,00,2,raw_ch1,raw_ch2,xor;
                            raw_ch1 = float(parts[2]) # PA1 - Fuerza (0 a 4095)
                            raw_ch2 = float(parts[3]) # PA4 - Humedad / IR (0 a 4095)
                            f = round((raw_ch1 / 4095.0) * 4.4, 2)
                            h = round(max(0.0, min(100.0, ((3700.0 - raw_ch2) / 2800.0) * 100.0)), 1)
                            d = round(min(25.0, (f / 4.4) * 18.0), 1)
                            v = round(0.03 + (0.35 if f > 2.5 else 0.0), 2)
                            read_success = True
                        elif len(parts) >= 4:
                            h = float(parts[0])
                            f = float(parts[1])
                            d = float(parts[2])
                            v = float(parts[3])
                            read_success = True
                except (ValueError, IndexError):
                    continue
                except Exception:
                    ser = None
                    with state_lock:
                        state["serial_connected"] = False
                        state["port"] = "SIN HARDWARE"
                    break

            with state_lock:
                if read_success:
                    state["hum"] = h
                    state["force"] = f
                    state["disp"] = d
                    state["vib"] = v
                    state["moment"] = round(f * 0.88, 2)
                    if len(parts) >= 8 and parts[0] == "00" and parts[1] == "6":
                        state["raw_fsr"] = raw_f
                        state["raw_ir"] = raw_ir
                        state["raw_soil"] = raw_soil
                        state["acc_x"] = acc_x
                        state["acc_y"] = acc_y
                        state["acc_z"] = acc_z
                        state["tilt"] = tilt_deg
                elif not state["cable_fault"] and not state["serial_connected"]:
                    # Sin hardware conectado: reportar DESCONECTADO (100% real, cero simulacion)
                    state["port"] = "SIN HARDWARE"
                    state["status"] = "DESCONECTADO"
                    state["ttf"] = "--"

                if read_success or state["cable_fault"]:
                    fs, status, ttf = compute_geotech(
                        state["hum"], state["force"], state["disp"], state["vib"], state["cable_fault"]
                    )
                    state["fs"] = fs
                    state["status"] = status
                    state["ttf"] = ttf
                state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # Guardar en base de datos cada 1 segundo (5 ciclos x 200 ms) cuando hay hardware
            db_counter += 1
            if db_counter >= 5:
                with state_lock:
                    snap = dict(state)
                save_reading(snap["hum"], snap["force"], snap["disp"], snap["vib"], snap["fs"], snap["status"], snap)
                db_counter = 0

            time.sleep(0.2) # 5 Hz update al frontend

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# -------------------------------------------------------------
# Rutas de la API y Servidor Web
# -------------------------------------------------------------
_PARENT_DIR = os.path.dirname(BASE_DIR)
WEB_DEPLOY_DIR = _PARENT_DIR if os.path.exists(os.path.join(_PARENT_DIR, "index.html")) else os.path.join(_PARENT_DIR, "sat_geo_web_deploy")

@app.route("/")
def index():
    index_path = os.path.join(WEB_DEPLOY_DIR, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(WEB_DEPLOY_DIR, "index.html")
    return render_template_string(HTML_TEMPLATE)

@app.route("/manifest.json")
def serve_manifest():
    return send_from_directory(WEB_DEPLOY_DIR, "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def serve_sw():
    return send_from_directory(WEB_DEPLOY_DIR, "sw.js", mimetype="application/javascript")

@app.route("/img/<path:filename>")
def serve_img(filename):
    return send_from_directory(os.path.join(WEB_DEPLOY_DIR, "img"), filename)

@app.route("/firmware/<path:filename>")
def serve_firmware(filename):
    return send_from_directory(os.path.join(WEB_DEPLOY_DIR, "firmware"), filename)

@app.route("/documentacion/<path:filename>")
def serve_docs(filename):
    return send_from_directory(os.path.join(WEB_DEPLOY_DIR, "documentacion"), filename)

@app.route("/matlab/<path:filename>")
def serve_matlab(filename):
    return send_from_directory(os.path.join(WEB_DEPLOY_DIR, "matlab"), filename)

@app.route("/sat_geo_android_app_kotlin.zip")
def serve_android_zip():
    return send_from_directory(WEB_DEPLOY_DIR, "sat_geo_android_app_kotlin.zip")

@app.route("/sat-geo-alerta.apk")
def serve_android_apk():
    return send_from_directory(WEB_DEPLOY_DIR, "sat-geo-alerta.apk")

@app.route("/api/export.csv")
def export_csv():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, momento, raw_fsr, force_n, raw_ir, disp_mm,
                   raw_soil, hum_pct, acc_x, acc_y, acc_z, tilt_deg, vib_g, fs, status
            FROM sensor_samples ORDER BY id ASC
        """)
        rows = c.fetchall()
    finally:
        if conn is not None:
            conn.close()
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["timestamp", "momento", "raw_fsr", "force_N", "raw_ir", "disp_mm", "raw_soil", "hum_pct", "acc_x", "acc_y", "acc_z", "tilt_deg", "vib_g", "FS", "status"])
    for r in rows:
        writer.writerow(["" if x is None else x for x in r])
    return app.response_class(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sat_geo_datos_reales_4_sensores.csv"}
    )

@app.route("/api/telemetry")
def get_telemetry():
    with state_lock:
        return jsonify(state)

def _bounded_float(val, lo, hi):
    num = float(val)
    if not math.isfinite(num):
        raise ValueError("Non-finite float")
    return max(lo, min(hi, num))

@app.route("/api/control", methods=["POST"])
def control():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "Invalid JSON object"}), 400
    try:
        with state_lock:
            if "sim_storm" in data:
                state["sim_storm"] = bool(data["sim_storm"])
                if not state["sim_storm"]:
                    state["hum"] = 20.0
                    state["force"] = 0.20
                    state["disp"] = 0.8
                    state["vib"] = 0.04
                    state["raw_fsr"] = 78
                    state["raw_ir"] = 120
                    state["raw_soil"] = 3250
                    state["acc_x"] = 1
                    state["acc_y"] = 0
                    state["acc_z"] = 256
                    state["tilt"] = 0.22
                    state["moment"] = 0.18
            if "cable_fault" in data:
                state["cable_fault"] = bool(data["cable_fault"])
            if "momento" in data and isinstance(data["momento"], str):
                clean_m = "".join(ch for ch in data["momento"][:40] if ch.isalnum() or ch in ("_", "-", " ")).lstrip("- ")
                if clean_m:
                    state["momento"] = clean_m
            if data.get("tare"):
                state["tare_requested"] = True
            if data.get("clear_samples"):
                try:
                    c_del = sqlite3.connect(DB_PATH, timeout=5.0)
                    c_del.execute("DELETE FROM sensor_samples")
                    c_del.commit()
                    c_del.close()
                except Exception as e:
                    print(f"Error clearing sensor_samples: {e}")
            if "set_hum" in data:
                state["hum"] = _bounded_float(data["set_hum"], 0.0, 100.0)
            if "set_force" in data:
                state["force"] = _bounded_float(data["set_force"], 0.0, 4.4)
            if "set_disp" in data:
                state["disp"] = _bounded_float(data["set_disp"], 0.0, 50.0)
            if "set_vib" in data:
                state["vib"] = _bounded_float(data["set_vib"], 0.0, 2.0)
            snapshot = dict(state)
        return jsonify({"success": True, "state": snapshot})
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid numeric parameter"}), 400

@app.route("/api/history")
def get_history():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT timestamp, hum, force, disp, vib, fs, status FROM telemetry ORDER BY id DESC LIMIT 50")
        rows = c.fetchall()
    finally:
        if conn is not None:
            conn.close()
    
    result = []
    for r in reversed(rows):
        result.append({
            "time": r[0].split(" ")[-1],
            "hum": r[1],
            "force": r[2],
            "disp": r[3],
            "vib": r[4],
            "fs": r[5],
            "status": r[6]
        })
    return jsonify(result)

@app.route("/api/qr")
def get_qr():
    ip = get_local_ip()
    port = 5000
    url = f"http://{ip}:{port}"
    
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#06b6d4", back_color="#050914")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return jsonify({"url": url, "qr_b64": f"data:image/png;base64,{b64}"})

# -------------------------------------------------------------
# Plantilla HTML5 / PWA Moderna Multiplataforma (PC + Celular)
# -------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SAT-GEO 4.0 Studio Pro</title>
    <!-- PWA Config -->
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#06b6d4">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="SAT-GEO Pro">
    <link rel="apple-touch-icon" href="/static/icons/icon-192.png">

    <!-- Tailwind & Fonts -->
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; background: #050914; color: #f8fafc; }
        .mono { font-family: 'JetBrains Mono', monospace; }
        .glass { background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(14px); border: 1.5px solid rgba(148, 163, 184, 0.18); }
        .glow-cyan { box-shadow: 0 0 24px rgba(34, 211, 238, 0.25); }
        .glow-rose { box-shadow: 0 0 30px rgba(244, 63, 94, 0.35); }
    </style>
</head>
<body class="min-h-screen pb-16 flex flex-col">

    <!-- Top Bar -->
    <header class="sticky top-0 z-50 glass border-b border-slate-800 px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-2.5">
            <div class="w-9 h-9 rounded-xl bg-cyan-500/20 border border-cyan-400 flex items-center justify-center text-cyan-300 font-black text-lg">
                🛰️
            </div>
            <div>
                <h1 class="text-base sm:text-lg font-black tracking-tight text-white flex items-center gap-2">
                    SAT-GEO 4.0 <span class="text-xs px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-400/30">STUDIO PRO</span>
                </h1>
                <p class="text-[10px] text-slate-400 font-mono flex items-center gap-1.5">
                    <span id="conn-dot" class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span id="conn-text">Servidor Conectado</span>
                </p>
            </div>
        </div>

        <div class="flex items-center gap-2">
            <button id="install-btn" class="hidden px-3 py-1.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-black text-xs sm:text-sm flex items-center gap-1.5 shadow-lg shadow-cyan-500/30">
                📲 Descargar App
            </button>
            <button onclick="openQrModal()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-bold text-xs sm:text-sm flex items-center gap-1">
                📱 QR Celular
            </button>
            <button onclick="speakAlert(true)" class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-rose-300 border border-slate-700 text-sm" title="Probar Voz IA">
                🔊
            </button>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl w-full mx-auto p-3 sm:p-5 space-y-4 flex-1">

        <!-- Top Banner: Factor de Seguridad & Estado Vial -->
        <div id="status-card" class="glass rounded-2xl p-4 sm:p-5 border-2 border-emerald-400 transition-all flex flex-col md:flex-row items-center justify-between gap-4">
            <div class="flex items-center gap-4 text-center md:text-left">
                <div id="status-icon" class="text-5xl sm:text-6xl">🟢</div>
                <div>
                    <span class="text-xs font-black uppercase tracking-widest text-slate-400">ESTADO DEL TALUD / MURO</span>
                    <h2 id="status-text" class="text-2xl sm:text-3xl font-black text-emerald-300">TERRENO ESTABLE</h2>
                    <p id="status-desc" class="text-xs sm:text-sm text-slate-300">Condiciones normales. Los 4 sensores reportan estabilidad física.</p>
                </div>
            </div>

            <div class="flex items-center gap-6 divide-x divide-slate-800 w-full md:w-auto justify-around md:justify-end">
                <div class="text-center px-3">
                    <span class="text-[10px] font-bold uppercase text-slate-400">Factor Seguridad</span>
                    <div id="fs-val" class="mono text-3xl sm:text-4xl font-black text-emerald-300">FS 2.35</div>
                </div>
                <div class="text-center px-3">
                    <span class="text-[10px] font-bold uppercase text-amber-300">Tiempo al Colapso</span>
                    <div id="ttf-val" class="mono text-2xl sm:text-3xl font-black text-white">∞</div>
                </div>
            </div>
        </div>

        <!-- Grid: Gemelo Digital 3D + 4 Indicadores -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
            
            <!-- Columna Izquierda: GEMELO DIGITAL ANIMADO (7 cols) -->
            <div class="lg:col-span-7 glass rounded-2xl p-4 flex flex-col justify-between">
                <div class="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
                    <h3 class="text-sm font-extrabold uppercase tracking-wider text-cyan-400 flex items-center gap-1.5">
                        <span>🎮</span> Gemelo Digital del Muro en Vivo
                    </h3>
                    <span id="twin-tag" class="mono text-[11px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">
                        ESTABLE
                    </span>
                </div>

                <!-- SVG Gemelo Digital Interactivo -->
                <div class="w-full bg-[#070e1e] rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center p-2">
                    <svg viewBox="0 0 500 270" class="w-full h-[220px] sm:h-[250px]">
                        <!-- Suelo base -->
                        <rect x="0" y="230" width="500" height="40" fill="#1e293b"/>
                        <!-- Montaña / Suelo detrás del muro -->
                        <polygon points="210,35 490,35 490,230 210,230" fill="#3d2109" stroke="#78350f" stroke-width="2"/>
                        <!-- Nivel de Agua que sube dinámicamente -->
                        <rect id="svg-water" x="210" y="190" width="280" height="40" fill="rgba(6, 182, 212, 0.6)" stroke="#22d3ee" stroke-width="1.5"/>
                        <!-- Sonda Humedad S1 -->
                        <rect x="330" y="20" width="24" height="15" rx="3" fill="#0284c7" stroke="#38bdf8"/>
                        <line x1="337" y1="35" x2="337" y2="120" stroke="#22d3ee" stroke-width="3"/>
                        <line x1="347" y1="35" x2="347" y2="120" stroke="#22d3ee" stroke-width="3"/>
                        <text x="342" y="15" fill="#38bdf8" font-size="10" font-weight="bold" text-anchor="middle">S1: Humedad (PA4)</text>

                        <!-- Flechas de Empuje S2 -->
                        <g id="svg-arrows" opacity="0.25">
                            <line x1="285" y1="120" x2="225" y2="120" stroke="#f59e0b" stroke-width="5"/>
                            <polygon points="225,113 212,120 225,127" fill="#f59e0b"/>
                            <line x1="285" y1="175" x2="225" y2="175" stroke="#f43f5e" stroke-width="5"/>
                            <polygon points="225,168 212,175 225,182" fill="#f43f5e"/>
                        </g>

                        <!-- Muro que rota/inclina según Sensor Sharp S3 -->
                        <g id="svg-wall-group" transform="rotate(0, 190, 230)">
                            <rect id="svg-wall" x="175" y="35" width="35" height="195" rx="3" fill="#10b981" stroke="#f8fafc" stroke-width="2"/>
                            <!-- Sensor FlexiForce en la cara interna -->
                            <circle cx="210" cy="145" r="9" fill="#fbbf24" stroke="#ffffff" stroke-width="1.5"/>
                            <text x="165" y="28" fill="#fbbf24" font-size="10" font-weight="bold" text-anchor="middle">S2: Fuerza</text>
                        </g>

                        <!-- Sensor Sharp Infrarrojo S3 en la izquierda -->
                        <rect x="30" y="65" width="32" height="24" rx="4" fill="#e11d48" stroke="#fda4af"/>
                        <line id="svg-laser" x1="62" y1="77" x2="175" y2="77" stroke="#fb7185" stroke-width="2.5" stroke-dasharray="5,4"/>
                        <text x="46" y="55" fill="#fda4af" font-size="10" font-weight="bold">S3: Sharp IR (PA2)</text>
                        <text id="svg-laser-txt" x="118" y="70" fill="#ffffff" font-size="10" font-weight="bold" text-anchor="middle">Δx = 0 mm</text>

                        <!-- Ondas sísmicas S4 -->
                        <circle id="svg-quake" cx="350" cy="230" r="6" fill="none" stroke="#c084fc" stroke-width="2" opacity="0.2"/>
                        <text x="420" y="250" fill="#c084fc" font-size="10" font-weight="bold" text-anchor="middle">S4: Sismo (STM32)</text>
                    </svg>
                </div>

                <div class="grid grid-cols-4 gap-2 text-center text-[11px] mono pt-2 font-bold">
                    <div class="bg-slate-900/90 p-1.5 rounded border border-slate-800 text-cyan-300">PA4: <span id="v-hum">2.5V</span></div>
                    <div class="bg-slate-900/90 p-1.5 rounded border border-slate-800 text-amber-300">PA1: <span id="v-force">0.3V</span></div>
                    <div class="bg-slate-900/90 p-1.5 rounded border border-slate-800 text-rose-300">PA2: <span id="v-disp">1.4V</span></div>
                    <div class="bg-slate-900/90 p-1.5 rounded border border-slate-800 text-purple-300">Sismo: <span id="v-vib">0.0g</span></div>
                </div>
            </div>

            <!-- Columna Derecha: TARJETAS DE LOS 4 SENSORES (5 cols) -->
            <div class="lg:col-span-5 grid grid-cols-2 gap-3">
                <!-- S1: Humedad -->
                <div class="glass rounded-xl p-3.5 border-l-4 border-l-cyan-400 flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-center text-xs text-slate-400 font-bold mb-1">
                            <span>💧 AGUA (TIERRA)</span>
                            <span class="text-cyan-400 font-mono">PA4</span>
                        </div>
                        <div id="card-hum" class="mono text-2xl sm:text-3xl font-black text-white">18%</div>
                    </div>
                    <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden mt-2">
                        <div id="bar-hum" class="bg-cyan-400 h-full w-[18%] transition-all duration-300"></div>
                    </div>
                </div>

                <!-- S2: Fuerza FlexiForce -->
                <div class="glass rounded-xl p-3.5 border-l-4 border-l-amber-400 flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-center text-xs text-slate-400 font-bold mb-1">
                            <span>🧱 EMPUJE MURO</span>
                            <span class="text-amber-400 font-mono">PA1</span>
                        </div>
                        <div id="card-force" class="mono text-2xl sm:text-3xl font-black text-white">0.20 N</div>
                    </div>
                    <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden mt-2">
                        <div id="bar-force" class="bg-amber-400 h-full w-[5%] transition-all duration-300"></div>
                    </div>
                </div>

                <!-- S3: Infrarrojo Sharp -->
                <div class="glass rounded-xl p-3.5 border-l-4 border-l-rose-400 flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-center text-xs text-slate-400 font-bold mb-1">
                            <span>📐 INCLINACIÓN</span>
                            <span class="text-rose-400 font-mono">PA2</span>
                        </div>
                        <div id="card-disp" class="mono text-2xl sm:text-3xl font-black text-white">0.5 mm</div>
                    </div>
                    <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden mt-2">
                        <div id="bar-disp" class="bg-rose-400 h-full w-[2%] transition-all duration-300"></div>
                    </div>
                </div>

                <!-- S4: Vibración Sísmica -->
                <div class="glass rounded-xl p-3.5 border-l-4 border-l-purple-400 flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-center text-xs text-slate-400 font-bold mb-1">
                            <span>📳 SISMO / CARGA</span>
                            <span class="text-purple-400 font-mono">STM32</span>
                        </div>
                        <div id="card-vib" class="mono text-2xl sm:text-3xl font-black text-white">0.04 g</div>
                    </div>
                    <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden mt-2">
                        <div id="bar-vib" class="bg-purple-400 h-full w-[4%] transition-all duration-300"></div>
                    </div>
                </div>

                <!-- Control Panel & Simulador de Emergencia -->
                <div class="col-span-2 glass rounded-xl p-3 space-y-2">
                    <span class="text-xs font-black uppercase text-slate-400 tracking-wider">PANEL DE CONTROL & PRUEBA EN VIVO</span>
                    <div class="grid grid-cols-2 gap-2">
                        <button onclick="toggleStorm()" id="btn-storm" class="py-2 px-3 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-400/50 font-bold text-xs transition flex items-center justify-center gap-1.5">
                            ⚡ Simular Tormenta
                        </button>
                        <button onclick="toggleFault()" id="btn-fault" class="py-2 px-3 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 border border-purple-400/50 font-bold text-xs transition flex items-center justify-center gap-1.5">
                            🔌 Desconectar Cable
                        </button>
                    </div>
                </div>
            </div>
        </div>

    </main>

    <!-- Modal QR para Conectar Celulares -->
    <div id="qr-modal" class="fixed inset-0 z-50 hidden bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass rounded-2xl p-6 max-w-sm w-full border border-cyan-400/50 text-center space-y-4">
            <h3 class="text-lg font-black text-white">Conecta tu Celular en Vivo</h3>
            <p class="text-xs text-slate-300">Escanea este código con la cámara de tu celular (debe estar en el mismo WiFi):</p>
            <div class="p-2 bg-[#050914] rounded-xl border border-slate-700 flex justify-center">
                <img id="qr-img" src="" alt="Código QR" class="w-48 h-48 rounded-lg">
            </div>
            <p id="qr-url" class="mono text-xs text-cyan-300 font-bold break-all"></p>
            <button onclick="closeQrModal()" class="w-full py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-bold text-sm">
                Cerrar
            </button>
        </div>
    </div>

    <!-- Script de PWA y Telemetría en Vivo -->
    <script>
        // Registrar Service Worker para PWA (instalable en celular)
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').then(reg => {
                console.log('PWA Service Worker registrado');
            });
        }

        let deferredPrompt;
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            const btn = document.getElementById('install-btn');
            btn.classList.remove('hidden');
            btn.addEventListener('click', () => {
                deferredPrompt.prompt();
                deferredPrompt.userChoice.then(() => {
                    btn.classList.add('hidden');
                });
            });
        });

        // Polling de Telemetría cada 200 ms (5 Hz)
        let lastStatus = "SEGURO";

        async function fetchTelemetry() {
            try {
                const res = await fetch('/api/telemetry');
                const data = await res.json();
                updateUI(data);
            } catch (err) {
                document.getElementById('conn-dot').className = "w-2 h-2 rounded-full bg-rose-500";
                document.getElementById('conn-text').textContent = "Reconectando...";
            }
        }

        function updateUI(d) {
            document.getElementById('conn-dot').className = "w-2 h-2 rounded-full bg-emerald-400 animate-pulse";
            document.getElementById('conn-text').textContent = d.serial_connected ? `STM32 (${d.port})` : "Modo Servidor Cloud";

            // Valores numéricos
            document.getElementById('card-hum').textContent = `${d.hum}%`;
            document.getElementById('card-force').textContent = `${d.force.toFixed(2)} N`;
            document.getElementById('card-disp').textContent = `${d.disp.toFixed(1)} mm`;
            document.getElementById('card-vib').textContent = `${d.vib.toFixed(2)} g`;

            document.getElementById('bar-hum').style.width = `${Math.min(100, d.hum)}%`;
            document.getElementById('bar-force').style.width = `${Math.min(100, (d.force / 4.4) * 100)}%`;
            document.getElementById('bar-disp').style.width = `${Math.min(100, (d.disp / 25) * 100)}%`;
            document.getElementById('bar-vib').style.width = `${Math.min(100, (d.vib / 1.5) * 100)}%`;

            // Voltajes
            document.getElementById('v-hum').textContent = `${(3.0 - (d.hum/100)*2.2).toFixed(2)}V`;
            document.getElementById('v-force').textContent = `${((d.force/4.4)*3.3).toFixed(2)}V`;
            document.getElementById('v-disp').textContent = `${(1.40 + (d.disp/25)*1.35).toFixed(2)}V`;
            document.getElementById('v-vib').textContent = `${d.vib.toFixed(2)}g`;

            // Gemelo Digital SVG
            const waterHeight = Math.max(10, Math.round((d.hum / 100) * 195));
            document.getElementById('svg-water').setAttribute('y', 230 - waterHeight);
            document.getElementById('svg-water').setAttribute('height', waterHeight);

            const tilt = -(d.disp * 0.45).toFixed(2);
            document.getElementById('svg-wall-group').setAttribute('transform', `rotate(${tilt}, 190, 230)`);
            document.getElementById('svg-laser-txt').textContent = `Δx = ${d.disp.toFixed(1)} mm`;

            document.getElementById('svg-arrows').setAttribute('opacity', Math.min(1, 0.2 + d.force / 4));
            document.getElementById('svg-quake').setAttribute('r', 6 + Math.round(d.vib * 12));
            document.getElementById('svg-quake').setAttribute('opacity', Math.min(1, 0.2 + d.vib));

            // Factor de Seguridad y Estado
            document.getElementById('fs-val').textContent = `FS ${d.fs.toFixed(2)}`;
            document.getElementById('ttf-val').textContent = d.ttf;

            const card = document.getElementById('status-card');
            const icon = document.getElementById('status-icon');
            const txt = document.getElementById('status-text');
            const desc = document.getElementById('status-desc');
            const wall = document.getElementById('svg-wall');
            const twinTag = document.getElementById('twin-tag');

            if (d.status === "COLAPSO") {
                card.className = "glass rounded-2xl p-4 sm:p-5 border-2 border-rose-500 glow-rose transition-all flex flex-col md:flex-row items-center justify-between gap-4";
                icon.textContent = "🚨";
                txt.textContent = "¡PELIGRO DE COLAPSO INMINENTE!";
                txt.className = "text-2xl sm:text-3xl font-black text-rose-400";
                desc.textContent = "Saturación de agua alta y deformación en progreso. Protocolo de evacuación activo.";
                wall.setAttribute('fill', '#f43f5e');
                twinTag.textContent = "¡COLAPSO!";
                twinTag.className = "mono text-[11px] px-2 py-0.5 rounded bg-rose-500/30 text-rose-200 font-bold";

                if (lastStatus !== "COLAPSO") {
                    speakAlert(false);
                }
            } else if (d.status === "PRECAUCION") {
                card.className = "glass rounded-2xl p-4 sm:p-5 border-2 border-amber-400 transition-all flex flex-col md:flex-row items-center justify-between gap-4";
                icon.textContent = "🟡";
                txt.textContent = "PRECAUCIÓN GEOTÉCNICA";
                txt.className = "text-2xl sm:text-3xl font-black text-amber-300";
                desc.textContent = "Infiltración de lluvia moderada o esfuerzo en aumento. Vigilancia de corona activada.";
                wall.setAttribute('fill', '#f59e0b');
                twinTag.textContent = "VIGILANCIA";
                twinTag.className = "mono text-[11px] px-2 py-0.5 rounded bg-amber-500/30 text-amber-200 font-bold";
            } else if (d.status === "DESCONECTADO") {
                card.className = "glass rounded-2xl p-4 sm:p-5 border-2 border-purple-400 transition-all flex flex-col md:flex-row items-center justify-between gap-4";
                icon.textContent = "🔌";
                txt.textContent = "SENSOR DESCONECTADO";
                txt.className = "text-2xl sm:text-3xl font-black text-purple-300";
                desc.textContent = "El sistema de autodiagnóstico detectó un circuito abierto en los cables de señal.";
                wall.setAttribute('fill', '#a855f7');
                twinTag.textContent = "WATCHDOG";
                twinTag.className = "mono text-[11px] px-2 py-0.5 rounded bg-purple-500/30 text-purple-200 font-bold";
            } else {
                card.className = "glass rounded-2xl p-4 sm:p-5 border-2 border-emerald-400 transition-all flex flex-col md:flex-row items-center justify-between gap-4";
                icon.textContent = "🟢";
                txt.textContent = "TERRENO ESTABLE";
                txt.className = "text-2xl sm:text-3xl font-black text-emerald-300";
                desc.textContent = "Condiciones normales. Los 4 sensores reportan estabilidad física.";
                wall.setAttribute('fill', '#10b981');
                twinTag.textContent = "ESTABLE";
                twinTag.className = "mono text-[11px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold";
            }

            lastStatus = d.status;
        }

        let isStorming = false;
        async function toggleStorm() {
            isStorming = !isStorming;
            const btn = document.getElementById('btn-storm');
            btn.textContent = isStorming ? "⏹️ Detener Tormenta" : "⚡ Simular Tormenta";
            await fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sim_storm: isStorming })
            });
        }

        let isFault = false;
        async function toggleFault() {
            isFault = !isFault;
            const btn = document.getElementById('btn-fault');
            btn.textContent = isFault ? "🔌 Reconectar Cable" : "🔌 Desconectar Cable";
            await fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ cable_fault: isFault })
            });
        }

        function speakAlert(manual = false) {
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const phrase = manual
                    ? "Sistema de Alerta Temprana SAT-GEO 4.0 Studio Pro en línea. Telemetría de 4 sensores transmitiendo en tiempo real."
                    : "Alerta crítica de derrumbe. Factor de seguridad en colapso. Deformación estructural detectada. Evacuar vía de inmediato.";
                const msg = new SpeechSynthesisUtterance(phrase);
                msg.lang = 'es-ES';
                msg.rate = 1.0;
                window.speechSynthesis.speak(msg);
            }
        }

        async function openQrModal() {
            const res = await fetch('/api/qr');
            const data = await res.json();
            document.getElementById('qr-img').src = data.qr_b64;
            document.getElementById('qr-url').textContent = data.url;
            document.getElementById('qr-modal').classList.remove('hidden');
        }

        function closeQrModal() {
            document.getElementById('qr-modal').classList.add('hidden');
        }

        setInterval(fetchTelemetry, 200);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    init_db()
    # Iniciar lector serial/simulador en hilo demonio
    t = threading.Thread(target=serial_worker, daemon=True)
    t.start()
    
    local_ip = get_local_ip()
    print("=" * 65)
    print("  >>> SAT-GEO 4.0 STUDIO PRO - SERVIDOR EN TIEMPO REAL INICIADO <<<")
    print("=" * 65)
    print(f"  [PC] Acceso Local:         http://localhost:5000")
    print(f"  [MOVIL] Acceso Celulares:  http://{local_ip}:5000")
    print("=" * 65)
    
    bind_host = os.environ.get("SATGEO_HOST", "127.0.0.1")
    app.run(host=bind_host, port=5000, debug=False)
