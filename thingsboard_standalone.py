import requests
import time
import random
import urllib3
 
# Vypnutie varovaní o SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
 
# 1. KONFIGURÁCIA
THINGSBOARD_TOKEN = "fhP2L84hYkP9dPuvrtyj"
THINGSBOARD_URL = f"https://eu.thingsboard.cloud/api/v1/{THINGSBOARD_TOKEN}/telemetry"
 
print("====================================================")
print("-> Štartujem test pre kompletnú telemetriu (EU Cloud)")
print(f"-> Smerujem na URL: {THINGSBOARD_URL}")
print("====================================================\n")
 
try:
    while True:
        # 1. Simulácia stavu systému (Náhodne vyberie, či systém beží alebo je vypnutý)
        # V praxi to bude reálny stav, napr. "RUNNING", "CLOSE", "HEATING", "COOLING"
        stavy = ["RUNNING", "RUNNING", "RUNNING", "CLOSE"] # Vyššia šanca, že systém beží
        aktualny_stav = random.choice(stavy)
        # 固定 parametre regulácie (konštanty, ktoré sa zvyčajne menia iba z webu)
        kp_hodnota = 4.5
        ki_hodnota = 0.2
        setpoint_hodnota = 24.0
        # 2. Generovanie logicky naviazaných náhodných dát
        if aktualny_stav == "CLOSE":
            pwm_hodnota = 0
            teplota_hodnota = round(random.uniform(21.0, 22.5), 2)  # Teplota klesne k izbovej
        else:
            pwm_hodnota = random.randint(80, 220)                   # Regulátor pracuje
            teplota_hodnota = round(random.uniform(23.5, 24.8), 2)  # Teplota osciluje okolo setpointu
        # 3. Vytvorenie kompletného JSON balíčka (Payload)
        payload = {
            "teplota": teplota_hodnota,
            "setpoint": setpoint_hodnota,
            "peltier_pwm": pwm_hodnota,
            "kp": kp_hodnota,
            "ki": ki_hodnota,
            "stav_systemu": aktualny_stav
        }
        headers = {"Content-Type": "application/json"}
        # 4. Odoslanie dát na ThingsBoard
        try:
            # Ponechaný vyšší timeout kvôli stabilite na školskej sieti/hotspote
            response = requests.post(THINGSBOARD_URL, json=payload, headers=headers, timeout=5, verify=False)
            if response.status_code == 200:
                print(f"[HTTP 200 OK] Dáta odoslané do EU cloudu!")
                print(f"               Balíček: {payload}\n")
            elif response.status_code == 401:
                print(f"[HTTP 401 Chyba] Neautorizovaný prístup! Skontroluj token.")
            else:
                print(f"[HTTP CHYBA] Server vrátil kód: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"[CHYBA SIETE] Problém s pripojením: {e}")
        # Posielame každé 3 sekundy
        time.sleep(3)
 
except KeyboardInterrupt:
    print("\n-> Testovanie bolo ukončené.")