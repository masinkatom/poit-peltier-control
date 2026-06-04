from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import mysql.connector
import json
import os
import requests
import urllib3

# Vypnutie varovaní o SSL (z testovacieho skriptu)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# DATABASE CONFIGURATION
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',          
    'password': 'heslo',     # Uprav podľa tvojho hesla do MariaDB
    'database': 'PELTIER_CONTROL'
}

# THINGSBOARD CONFIGURATION
THINGSBOARD_TOKEN = "fhP2L84hYkP9dPuvrtyj"
THINGSBOARD_URL = f"https://eu.thingsboard.cloud/api/v1/{THINGSBOARD_TOKEN}/telemetry"

current_measurement_id = None

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


@app.route('/')
def index():
    return render_template('index.html')


# ============================================================
# POMOCNÁ FUNKCIA: ASYNCHRÓNNE ODOSIELANIE NA THINGSBOARD
# ============================================================
def odosli_na_thingsboard_background(payload):
    try:
        headers = {"Content-Type": "application/json"}
        # Ponechaný timeout 5s a verify=False podľa tvojho testovacieho skriptu
        response = requests.post(THINGSBOARD_URL, json=payload, headers=headers, timeout=5, verify=False)
        if response.status_code == 200:
            print(f"[ThingsBoard] Dáta úspešne odoslané do cloudu.")
        elif response.status_code == 401:
            print(f"[ThingsBoard CHYBA] Neautorizovaný prístup! Skontroluj TOKEN.")
        else:
            print(f"[ThingsBoard CHYBA] Server vrátil kód: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ThingsBoard CHYBA SIETE] Nepodarilo sa nadviazať spojenie: {e}")


# ============================================================
# MODIFIKOVANÁ ROUTE: EXPORT DO ŠTRUKTÚROVANÉHO JSON SÚBORU
# ============================================================
@app.route('/ulozit_json_server', methods=['POST'])
def ulozit_json_server():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) # Dáta dostaneme ako slovníky (objekty)
        
        # Spojíme tabuľky, aby sme získali info o meraní aj prislúchajúcu telemetriu
        query = """
            SELECT 
                m.id AS m_id, 
                m.start_timestamp, 
                m.end_timestamp,
                t.timestamp AS t_timestamp, 
                t.system_state, 
                t.temperature, 
                t.setpoint, 
                t.peltier_pwm, 
                t.kp, 
                t.ki
            FROM Measurement m
            LEFT JOIN Telemetry t ON m.id = t.id_measurement
            ORDER BY m.id ASC, t.timestamp ASC
        """
        cursor.execute(query)
        vysledky = cursor.fetchall()
        
        cursor.close()
        conn.close()

        if not vysledky:
            return jsonify({"status": "chyba", "sprava": "V DB nie sú žiadne dáta na uloženie."}), 400

        # Algoritmus na zoskupenie dát podľa ID merania do požadovanej štruktúry
        strukturovane_data = {}
        
        for riadok in vysledky:
            meranie_id = riadok['m_id']
            
            # Ak meranie ešte nemáme v našom slovníku, vytvoríme preň základnú štruktúru
            if meranie_id not in strukturovane_data:
                strukturovane_data[meranie_id] = {
                    "measurement": {
                        "id": meranie_id,
                        "start_timestamp": riadok['start_timestamp'].strftime("%Y-%m-%d %H:%M:%S") if riadok['start_timestamp'] else None,
                        "end_timestamp": riadok['end_timestamp'].strftime("%Y-%m-%d %H:%M:%S") if riadok['end_timestamp'] else None,
                        "measurement_data": []
                    }
                }
            
            # Ak k tomuto meraniu existuje telemetria (nie je prázdne kvôli LEFT JOIN), pridáme ju
            if riadok['t_timestamp'] is not None:
                telemetria_bod = {
                    "timestamp": riadok['t_timestamp'].strftime("%Y-%m-%d %H:%M:%S"),
                    "system_state": riadok['system_state'],
                    "temperature": float(riadok['temperature']) if riadok['temperature'] is not None else None,
                    "setpoint": float(riadok['setpoint']) if riadok['setpoint'] is not None else None,
                    "peltier_pwm": riadok['peltier_pwm'],
                    "kp": float(riadok['kp']) if riadok['kp'] is not None else None,
                    "ki": float(riadok['ki']) if riadok['ki'] is not None else None,
                    "id_measurement": meranie_id
                }
                strukturovane_data[meranie_id]["measurement"]["measurement_data"].append(telemetria_bod)

        # Prevedieme slovník na čistý zoznam (Array) objektov tak, ako si požadoval
        finalny_list_json = list(strukturovane_data.values())

        # Názov cieľového súboru
        nazov_suboru = "energia_historia.json"

        # Zápis na disk servera
        with open(nazov_suboru, 'w', encoding='utf-8') as f:
            json.dump(finalny_list_json, f, indent=2, ensure_ascii=False)

        print(f"[SERVER] História úspešne exportovaná do štruktúry a uložená: {os.path.abspath(nazov_suboru)}")
        return jsonify({"status": "ok", "sprava": f"Dáta úspešne uložené na serveri do {nazov_suboru}!"})

    except Exception as e:
        print(f"[CHYBA EXPORTU] {e}")
        return jsonify({"status": "chyba", "sprava": str(e)}), 500


# ============================================================
# OBYČAJNÁ ROUTE: TU SI WEB VYŽIADA DATA PRE HISTORICKÝ GRAF
# ============================================================
@app.route('/nacitat_historiu', methods=['GET'])
def nacitat_historiu():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Vytiahneme telemetriu zoradenú podľa času pre plynulé vykreslenie čiary grafu
        cursor.execute("""
            SELECT timestamp, temperature, peltier_pwm 
            FROM Telemetry 
            ORDER BY timestamp ASC
        """)
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Sformátujeme datetime objekty na text, aby ich JavaScript spracoval
        for r in data:
            if r['timestamp']:
                r['cas'] = r['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                del r['timestamp'] # nahradíme kľúčom 'cas', ktorý očakáva index.html
            if r['temperature']:
                r['teplota'] = float(r['temperature'])
                del r['temperature']
                
        return jsonify(data)
    except Exception as e:
        print(f"[CHYBA NAČÍTANIA HISTÓRIE] {e}")
        return jsonify([]), 500

@app.route('/energia_historia.json')
def get_measurements():
    try:
        with open('energia_historia.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except FileNotFoundError:
        return jsonify([])

# ============================================================
# WEBSOCKET: PRIJÍMANIE LIVE TELEMETRIE Z ESP32, ZÁPIS DO DB A THINGSBOARD
# ============================================================
@socketio.on('telemetria')
def handle_telemetria(data_z_esp):
    global current_measurement_id
    if not data_z_esp:
        return
        
    stav_esp = data_z_esp.get("stav_systemu")
    print(f"<- [ESP32 Telemetria] Stav: {stav_esp} | Teplota: {data_z_esp.get('teplota')}°C")
    
    # --------------------------------------------------------
    # INTEGRÁCIA THINGSBOARD: Príprava a odoslanie balíčka v background tasku
    # --------------------------------------------------------
    tb_payload = {
        "teplota": float(data_z_esp.get("teplota")) if data_z_esp.get("teplota") is not None else None,
        "setpoint": float(data_z_esp.get("setpoint")) if data_z_esp.get("setpoint") is not None else None,
        "peltier_pwm": data_z_esp.get("peltier_pwm"),
        "kp": float(data_z_esp.get("kp")) if data_z_esp.get("kp") is not None else None,
        "ki": float(data_z_esp.get("ki")) if data_z_esp.get("ki") is not None else None,
        "stav_systemu": stav_esp
    }
    # Spustí sa na pozadí, nečaká sa na HTTP odpoveď ThingsBoardu
    socketio.start_background_task(odosli_na_thingsboard_background, tb_payload)
    # --------------------------------------------------------

    # Automatický štart/stop relácie merania v tabuľke Measurement
    if stav_esp == "START" and current_measurement_id is None:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Measurement (start_timestamp) VALUES (NOW())")
            conn.commit()
            current_measurement_id = cursor.lastrowid
            cursor.close()
            conn.close()
            print(f"[DB] Začalo meranie pod ID: {current_measurement_id}")
        except Exception as e:
            print(f"[DB CHYBA] Zlyhal štart merania: {e}")

    elif stav_esp == "STOP" and current_measurement_id is not None:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE Measurement SET end_timestamp = NOW() WHERE id = %s", (current_measurement_id,))
            conn.commit()
            cursor.close()
            conn.close()
            print(f"[DB] Meranie ID {current_measurement_id} bolo ukončené.")
            current_measurement_id = None
        except Exception as e:
            print(f"[DB CHYBA] Zlyhalo ukončenie merania: {e}")
            
    # Zápis live dát z telemetrie do tabuľky Telemetry (ak beží aktívne meranie)
    if current_measurement_id is not None:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            sql = """
                INSERT INTO Telemetry 
                (timestamp, system_state, temperature, setpoint, peltier_pwm, kp, ki, id_measurement)
                VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                stav_esp, 
                data_z_esp.get("teplota"), 
                data_z_esp.get("setpoint"),
                data_z_esp.get("peltier_pwm"), 
                data_z_esp.get("kp"), 
                data_z_esp.get("ki"), 
                current_measurement_id
            )
            cursor.execute(sql, values)
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[DB CHYBA] Nepodarilo sa zapísať telemetriu: {e}")

    # Preposlanie dát na webové rozhranie (pre graf, boxy, budíky)
    socketio.emit('aktualne_data', data_z_esp)


# ============================================================
# HTTP POST: ODOSIELANIE PRÍKAZOV Z WEBU DO ESP32
# ============================================================
@app.route('/odosli_prikaz', methods=['POST'])
def odosli_prikaz():
    data_z_webu = request.json
    print(f">> [Web Príkaz] Posielam do ESP32: {data_z_webu}")
    
    try:
        socketio.emit('riadenie', data_z_webu)
        return jsonify({"status": "ok", "sprava": "Príkaz odoslaný úspešne."})
    except Exception as e:
        return jsonify({"status": "chyba", "sprava": str(e)}), 500


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)