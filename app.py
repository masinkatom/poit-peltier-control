from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import requests
import json
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Konfigurácia IP adresy ESP32
ESP32_IP = "http://192.168.1.104" 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/telemetria', methods=['POST'])
def prijmi_telemetriu():
    data_z_esp = request.json
    if not data_z_esp:
        return jsonify({"status": "chyba", "sprava": "Ziadne data"}), 400
        
    print(f"<- [ESP32] Teplota: {data_z_esp.get('teplota')}°C, PWM: {data_z_esp.get('peltier_pwm')}")
    
    try:
        zaznam = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stav_systemu": data_z_esp.get("stav_systemu"),
            "teplota": data_z_esp.get("teplota"),
            "peltier_pwm": data_z_esp.get("peltier_pwm"),
            "kp": data_z_esp.get("kp"),
            "ki": data_z_esp.get("ki")
        }
        with open("energia_historia.json", "a") as f:
            f.write(json.dumps(zaznam) + "\n")
    except Exception as e:
        print(f"Chyba zápisu do súboru: {e}")

    socketio.emit('aktualne_data', data_z_esp)
    return jsonify({"status": "dorucene_na_server"}), 200

@app.route('/odosli_prikaz', methods=['POST'])
def odosli_prikaz():
    data_z_webu = request.json
    print(f">> [Web] Preposielam do ESP32: {data_z_webu}")
    
    try:
        url = f"{ESP32_IP}/api/riadenie"
        # Prepošle presne to, čo prišlo z webu (buď iba prikaz, alebo iba setpoint+kp+ki)
        odpoved_esp = requests.post(url, json=data_z_webu, timeout=3)
        
        if odpoved_esp.status_code == 200:
            return jsonify({"status": "ok", "sprava": "Odoslané úspešne"})
        else:
            return jsonify({"status": "chyba", "sprava": f"ESP vrátilo kód {odpoved_esp.status_code}"})
            
    except requests.exceptions.RequestException as e:
        print(f"Chyba spojenia s ESP32: {e}")
        return jsonify({"status": "chyba", "sprava": "ESP32 nereaguje."})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
