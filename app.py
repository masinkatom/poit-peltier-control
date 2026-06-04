from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import mysql.connector
import json
import time

app = Flask(__name__)
# Explicitly forcing eventlet to avoid any socket errors
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# DATABASE CONFIGURATION
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',          # Change to your MariaDB username if different
    'password': 'heslo',  # Change to your MariaDB password
    'database': 'PELTIER_CONTROL'
}

# Global variable to track the current active measurement ID
current_measurement_id = None

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


@app.route('/')
def index():
    return render_template('index.html')


# 1. RECEIVING TELEMETRY FROM ESP32 VIA WEBSOCKET
@socketio.on('telemetria')
def handle_telemetria(data_z_esp):
    global current_measurement_id
    if not data_z_esp:
        return
        
    print(f"<- [ESP32 WS] Teplota: {data_z_esp.get('teplota')}°C | PWM: {data_z_esp.get('peltier_pwm')} | Error: {data_z_esp.get('error')} | Setpoint: {data_z_esp.get('setpoint')}")
    
    # Only save to DB if a measurement session is actively running (START has been pressed)
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
                data_z_esp.get("stav_systemu"),
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
            print(f"[DB] Telemetria uložená pod ID merania: {current_measurement_id}")
            
        except Exception as e:
            print(f"[DB CHYBA] Zápis telemetrie zlyhal: {e}")
    else:
        print("[DB] Meranie nie je aktívne (STOP stav), dáta sa neukladajú.")

    # Instantly pass data to the web frontend
    socketio.emit('aktualne_data', data_z_esp)


# 2. SENDING COMMANDS AND HANDLING MEASUREMENT SESSIONS
@app.route('/odosli_prikaz', methods=['POST'])
def odosli_prikaz():
    global current_measurement_id
    data_z_webu = request.json
    prikaz = data_z_webu.get('prikaz') # In your code logic, this contains 'START' or 'STOP'
    
    print(f">> [Web] Preposielam do ESP32 cez WebSocket: {data_z_webu}")
    
    try:
        # --- MARIADB LOGIC FOR START / STOP ---
        if prikaz == 'START' and current_measurement_id is None:
            # Create a brand new measurement session record
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Measurement (start_timestamp) VALUES (NOW())")
            conn.commit()
            
            current_measurement_id = cursor.lastrowid # Capture the generated primary key (id)
            print(f"[DB] Spustené NOVÉ meranie. Priradené ID: {current_measurement_id}")
            
            cursor.close()
            conn.close()

        elif prikaz == 'STOP' and current_measurement_id is not None:
            # End the current active measurement session by writing end_timestamp
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE Measurement SET end_timestamp = NOW() WHERE id = %s", 
                (current_measurement_id,)
            )
            conn.commit()
            print(f"[DB] Ukončené meranie s ID: {current_measurement_id}. Čas konca zapísaný.")
            
            current_measurement_id = None # Clear tracking state
            
            cursor.close()
            conn.close()
        # --------------------------------------

        # Broadcast the control configurations over to the ESP32
        socketio.emit('riadenie', data_z_webu)
        return jsonify({"status": "ok", "sprava": "Odoslané úspešne cez WebSocket a DB aktualizovaná."})
        
    except Exception as e:
        print(f"Chyba pri spracovaní príkazu / DB operácii: {e}")
        return jsonify({"status": "chyba", "sprava": f"Chyba na strane servera: {e}"}), 500


if __name__ == '__main__':
    # Server sa musí spúšťať cez socketio, aby WebSockety fungovali správne
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)