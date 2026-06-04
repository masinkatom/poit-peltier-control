from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO
import requests
import json
import time
import sqlite3
import csv
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Konfigurácia IP adresy ESP32
ESP32_IP = "http://192.168.1.109" 

DB_FILE = "data.db"
CSV_FILE = "archiv_dat.csv"

# Globálna premenná na sledovanie posledného stavu (pre reset CSV session)
posledny_znamy_stav = "CLOSE"

# ==========================================
# INICIALIZÁCIA DATABÁZY A SÚBORU
# ==========================================
def init_storage():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # PRIDANÝ STĹPEC: setpoint
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            stav_systemu TEXT,
            teplota REAL,
            setpoint REAL,
            peltier_pwm INTEGER,
            kp REAL,
            ki REAL
        )
    """)
    conn.commit()
    conn.close()

    if not os.path.exists(CSV_FILE):
        vymaz_a_resetuj_csv()

def vymaz_a_resetuj_csv():
    """Vymaže staré CSV a pripraví čistú hlavičku s novým stĺpcom Setpoint"""
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # PRIDANÝ STĹPEC: Cieľová Teplota [°C]
        writer.writerow(["Timestamp", "Stav Systemu", "Teplota [°C]", "Cieľová Teplota [°C]", "Peltier PWM", "Kp", "Ki"])
    print("-> CSV súbor bol vyčistený a pripravený na novú session.")

init_storage()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/telemetria', methods=['POST'])
def prijmi_telemetriu():
    global posledny_znamy_stav
    data_z_esp = request.json
    if not data_z_esp:
        return jsonify({"status": "chyba", "sprava": "Ziadne data"}), 400
        
    print(f"<- [ESP32] T: {data_z_esp.get('teplota')}°C, Setpoint: {data_z_esp.get('setpoint')}°C, PWM: {data_z_esp.get('peltier_pwm')}, Stav: {data_z_esp.get('stav_systemu')}")
    
    # 1. Slovenská časová pečiatka a premenné
    now = time.strftime("%d.%m.%Y %H:%M:%S")
    stav = data_z_esp.get("stav_systemu", "CLOSE")
    teplota = data_z_esp.get("teplota")
    setpoint = data_z_esp.get("setpoint") # Vytiahnutie setpointu z ESP32
    pwm = data_z_esp.get("peltier_pwm")
    kp = data_z_esp.get("kp")
    ki = data_z_esp.get("ki")
    
    # Detekcia novej session pre CSV
    if posledny_znamy_stav == "CLOSE" and stav != "CLOSE":
        vymaz_a_resetuj_csv()
    
    posledny_znamy_stav = stav

    # Zápis prebieha iba ak stav nie je CLOSE
    if stav != "CLOSE":
        # 2. Zápis do SQLite Databázy (vrátane setpointu)
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO telemetria (timestamp, stav_systemu, teplota, setpoint, peltier_pwm, kp, ki)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, stav, teplota, setpoint, pwm, kp, ki))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Chyba zápisu do databázy: {e}")

        # 3. Zápis do CSV súboru (vrátane setpointu)
        try:
            with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([now, stav, teplota, setpoint, pwm, kp, ki])
        except Exception as e:
            print(f"Chyba zápisu do CSV: {e}")
    else:
        print("-> Systém je v stave CLOSE. Zápis do DB a CSV preskočený.")

    # Poslanie kompletných dát na web
    socketio.emit('aktualne_data', data_z_esp)
    return jsonify({"status": "dorucene_na_server"}), 200

@app.route('/odosli_prikaz', methods=['POST'])
def odosli_prikaz():
    data_z_webu = request.json
    try:
        url = f"{ESP32_IP}/api/riadenie"
        odpoved_esp = requests.post(url, json=data_z_webu, timeout=3)
        if odpoved_esp.status_code == 200:
            return jsonify({"status": "ok", "sprava": "Odoslané úspešne"})
        else:
            return jsonify({"status": "chyba", "sprava": f"ESP vrátilo kód {odpoved_esp.status_code}"})
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "chyba", "sprava": "ESP32 nereaguje."})

# ==========================================
# ENDPOINTY PRE HISTÓRIU A STIAHNUTIE
# ==========================================
@app.route('/api/historia', methods=['GET'])
def ziskaj_historiu():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, stav_systemu, teplota, setpoint, peltier_pwm, kp, ki FROM telemetria ORDER BY id DESC LIMIT 20")
    rows = cursor.fetchall()
    conn.close()
    rows.reverse()
    historia = []
    for row in rows:
        historia.append({
            "timestamp": row[0], 
            "stav_systemu": row[1], 
            "teplota": row[2], 
            "setpoint": row[3], # Pridané do histórie
            "peltier_pwm": row[4], 
            "kp": row[5], 
            "ki": row[6]
        })
    return jsonify(historia)

@app.route('/stiahnut/csv', methods=['GET'])
def stiahni_csv():
    if os.path.exists(CSV_FILE):
        return send_file(CSV_FILE, as_attachment=True)
    return "Súbor neexistuje", 404

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
