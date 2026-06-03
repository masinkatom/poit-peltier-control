from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import json
import time

app = Flask(__name__)
# Povolenie WebSocket komunikácie
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/')
def index():
    return render_template('index.html')

# 1. PRIJMANIE TELEMETRIE Z ESP32 CEZ WEBSOCKET
@socketio.on('telemetria')
def handle_telemetria(data_z_esp):
    if not data_z_esp:
        return
        
    print(f"<- [ESP32 WS] Teplota: {data_z_esp.get('teplota')}°C | PWM: {data_z_esp.get('peltier_pwm')} | Error: {data_z_esp.get('error')} | Setpoint: {data_z_esp.get('setpoint')}")
    
    # Zápis do JSON histórie (doplnený o error a setpoint podľa požiadavky)
    try:
        zaznam = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stav_systemu": data_z_esp.get("stav_systemu"),
            "teplota": data_z_esp.get("teplota"),
            "peltier_pwm": data_z_esp.get("peltier_pwm"),
            "error": data_z_esp.get("error"),
            "setpoint": data_z_esp.get("setpoint"),
            "kp": data_z_esp.get("kp"),
            "ki": data_z_esp.get("ki")
        }
        with open("energia_historia.json", "a") as f:
            f.write(json.dumps(zaznam) + "\n")
    except Exception as e:
        print(f"Chyba zápisu do súboru: {e}")

    # Okamžité preposlanie dát na webový frontend (index.html)
    socketio.emit('aktualne_data', data_z_esp)


# 2. ODOSIELANIE PRÍKAZOV DO ESP32 CEZ WEBSOCKET
@app.route('/odosli_prikaz', methods=['POST'])
def odosli_prikaz():
    data_z_webu = request.json
    print(f">> [Web] Preposielam do ESP32 cez WebSocket: {data_z_webu}")
    
    try:
        # Miesto knižnice requests posielame správu cez WebSocket broadcast
        # Zachytia ju všetky pripojené zariadenia (vrátane ESP32 počúvajúceho na udalosť 'riadenie')
        socketio.emit('riadenie', data_z_webu)
        return jsonify({"status": "ok", "sprava": "Odoslané úspešne cez WebSocket"})
        
    except Exception as e:
        print(f"Chyba pri WebSocket distribúcii: {e}")
        return jsonify({"status": "chyba", "sprava": "Chyba na strane WebSocket servera."}), 500


if __name__ == '__main__':
    # Server sa musí spúšťať cez socketio, aby WebSockety fungovali správne
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)