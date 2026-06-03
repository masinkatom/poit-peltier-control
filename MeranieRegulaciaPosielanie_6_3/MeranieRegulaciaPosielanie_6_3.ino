#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ==========================================
// HARDVÉR SETUP (SENZOR DS18B20 & PELTIER)
// ==========================================
#define ONE_WIRE_BUS 27
#define PELTIER_PIN 4
#define PWM_FREQ 10
#define PWM_RESOLUTION 8  // Rozsah 0–255

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// ==========================================
// KONFIGURÁCIA SIETE
// ==========================================
const char* ssid = "D209"; 
const char* password = "pivolinD209"; 

// URL servera (Port 5000)
const char* serverUrl = "http://192.168.1.94:5000/api/telemetria"; 

WebServer espServer(80);

// ==========================================
// GLOBÁLNE PREMENNÉ REGULÁCIE (ZJEDNOTENÉ)
// ==========================================
String aktualny_stav = "STOP"; // Stavy z webu: OPEN, START, STOP, CLOSE

float cielova_teplota = 24.0;  // Setpoint prepisovaný z webu
float konstant_kp = 50.0;     // Kp prepisované z webu
float konstant_ki = 0.4;      // Ki prepisované z webu

float temperature = 0;
float error = 0;
float integral = 0;
float output = 0;

// Časovanie pre slučku riadenia a telemetrie (5 sekúnd)
unsigned long lastControl = 0;
const int sampleTime = 5000; 

// Deklarácie funkcií
void spustiRegulaciuAOdosliData();
void handleRiadenie();

// ==========================================
// SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Inicializácia fyzického senzora teploty
  sensors.begin();

  // Inicializácia hardvérového PWM pre Peltier (Nový Core 3.x API)
  ledcAttach(PELTIER_PIN, PWM_FREQ, PWM_RESOLUTION);
  ledcWrite(PELTIER_PIN, 0); 

  // Pripájanie na Wi-Fi sieť
  Serial.println("");
  Serial.print("Pripajam sa na Wi-Fi: ");
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWi-Fi úspešne pripojené!");
  Serial.print("IP adresa ESP32: ");
  Serial.println(WiFi.localIP());

  // Registrácia API cesty pre prichádzajúce povely z Flasku
  espServer.on("/api/riadenie", HTTP_POST, handleRiadenie);
  espServer.begin();
  Serial.println("ESP32 server spustený a pripravený na riadenie...");
}

// ==========================================
// MAIN LOOP
// ==========================================
void loop() {
  espServer.handleClient();

  if (millis() - lastControl >= sampleTime) {
    lastControl = millis();
    spustiRegulaciuAOdosliData();
  }
}

// ==========================================
// HLAVNÁ LOGIKA: REÁLNY SENZOR -> REGULÁCIA -> TELEMETRIA
// ==========================================
void spustiRegulaciuAOdosliData() {
  
  // 1. REÁLNE ČÍTANIE HODNÔT ZO SENZORA DS18B20
  sensors.requestTemperatures();
  float dallasTemp = sensors.getTempCByIndex(0);
  
  // Kontrola, či je senzor v poriadku zapojený
  if (dallasTemp == DEVICE_DISCONNECTED_C) {
    Serial.println("[CHYBA] Senzor teploty je odpojený!");
    // V prípade odpojenia senzora nevypočítavame nezmysly, ale pošleme núdzovú nulu
    temperature = 0.0; 
  } else {
    temperature = dallasTemp;
  }

  // 2. PI REGULÁTOR - MATEMATIKA PRE KÚRENIE (Beží iba pri stave START)
  if (aktualny_stav == "START") {
    // KÚRENIE: Odchýlka = Želaná - Aktuálna
    error = abs(cielova_teplota - temperature);
    integral += error;

    // Anti-windup ošetrenie integrálnej zložky
    float maxIntegral = 255.0 / konstant_ki;
    if (integral > maxIntegral) integral = maxIntegral;
    if (integral < 0) integral = 0;

    // Výpočet akčného zásahu
    output = (konstant_kp * error) + (konstant_ki * integral);

    // Striktné hardvérové limity PWM
    if (output > 255) output = 255;
    if (output < 0) output = 0;

  } else {
    // Pri stavoch STOP, OPEN a CLOSE sa regulácia kompletne nuluje a vypína
    output = 0;
    integral = 0; 
    error = 0;
  }

  // Zápis reálneho vypočítaného výkonu na Peltier pin 15
  ledcWrite(PELTIER_PIN, (int)output);

  // Výpis do Sériového monitoru pre okamžitú kontrolu na stole
  Serial.printf("[STAV: %s] Reálna Temp: %.2f °C | Setpoint: %.1f | Error: %.2f | Výkon PWM: %d\n",
                aktualny_stav.c_str(), temperature, cielova_teplota, error, (int)output);

  // 3. ODOSIELANIE TELEMETRIE DO FLASK SERVERA
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl); 
    http.addHeader("Content-Type", "application/json");

    char jsonBuffer[256];
    snprintf(jsonBuffer, sizeof(jsonBuffer),
             "{\"stav_systemu\":\"%s\",\"teplota\":%.2f,\"peltier_pwm\":%d,\"kp\":%.1f,\"ki\":%.1f}",
             aktualny_stav.c_str(), temperature, (int)output, konstant_kp, konstant_ki);

    int httpResponseCode = http.POST((uint8_t*)jsonBuffer, strlen(jsonBuffer));
    http.end(); // Uzatvorenie HTTP spojenia
  }
}

// ==========================================
// ROBUSTNÉ PARSOVANIE PRICHÁDZAJÚCICH DÁT Z WEBU
// ==========================================
void handleRiadenie() {
  if (espServer.hasArg("plain")) {
    String prijaty_json = espServer.arg("plain");
    Serial.println("\n<- [Flask] Prijaté dáta z webu: " + prijaty_json);

    bool zmena = false;

    // 1. Kontrola zmeny stavu / príkazu (START, STOP, OPEN, CLOSE)
    int idxPrikaz = prijaty_json.indexOf("\"prikaz\"");
    if (idxPrikaz != -1) {
      int startHladania = prijaty_json.indexOf(":", idxPrikaz);
      int start = prijaty_json.indexOf("\"", startHladania) + 1;
      int koniec = prijaty_json.indexOf("\"", start);
      
      if (start > 0 && koniec > start) {
        aktualny_stav = prijaty_json.substring(start, koniec);
        aktualny_stav.trim(); // Vyčistí biele znaky
        zmena = true;
      }
    }

    // 2. Kontrola a prepis Target Setpointu
    int idxSetpoint = prijaty_json.indexOf("\"setpoint\":");
    if (idxSetpoint != -1) {
      int start = idxSetpoint + 11;
      int koniec = prijaty_json.indexOf(",", start);
      if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
      cielova_teplota = prijaty_json.substring(start, koniec).toFloat();
      zmena = true;
    }

    // 3. Kontrola a prepis konštanty Kp
    int idxKp = prijaty_json.indexOf("\"kp\":");
    if (idxKp != -1) {
      int start = idxKp + 5;
      int koniec = prijaty_json.indexOf(",", start);
      if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
      konstant_kp = prijaty_json.substring(start, koniec).toFloat();
      zmena = true;
    }

    // 4. Kontrola a prepis konštanty Ki
    int idxKi = prijaty_json.indexOf("\"ki\":");
    if (idxKi != -1) {
      int start = idxKi + 5;
      int koniec = prijaty_json.indexOf(",", start);
      if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
      konstant_ki = prijaty_json.substring(start, koniec).toFloat();
      zmena = true;
    }

    // Ak sa dáta zmenili, vypíšeme rekapituláciu do monitoru
    if (zmena) {
      Serial.printf("[UPDATE] Úspešne zmenené -> Stav: %s | Setpoint: %.1f | Kp: %.1f | Ki: %.1f\n", 
                    aktualny_stav.c_str(), cielova_teplota, konstant_kp, konstant_ki);
    }

    espServer.send(200, "application/json", "{\"status\":\"ok\"}");
  } else {
    espServer.send(400, "application/json", "{\"status\":\"chyba\"}");
  }
}