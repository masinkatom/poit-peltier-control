#include <WiFi.h>
#include <WebSocketsClient.h> // POTREBNÁ KNIŽNICA: "WebSockets" od Links2004
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
// KONFIGURÁCIA SIETE A WEBSOCKET SERVERA
// ==========================================
const char* ssid = "D209"; 
const char* password = "pivolinD209"; 

// IP adresa a port tvojho Flask servera
const char* ws_host = "192.168.1.113"; 
const int ws_port = 5000;
// URL cesta pre komunikáciu so Socket.io v4 backendom
const char* ws_url = "/socket.io/?EIO=4&transport=websocket";

WebSocketsClient webSocket;

// ==========================================
// GLOBÁLNE PREMENNÉ REGULÁCIE (ZJEDNOTENÉ)
// ==========================================
String aktualny_stav = "CLOSE"; 

float cielova_teplota = 24.0;  
float konstant_kp = 100.0;     
float konstant_ki = 0.5;      

float temperature = 0;
float error = 0;
float integral = 0;
float output = 0;

// ROZDELENÉ ČASOVAČE
unsigned long lastControl = 0;
const int sampleTimePID = 1000; // PID regulácia každú 1 sekundu

unsigned long lastTelemetry = 0;
const int sampleTimeWS = 5000;  // WebSockets telemetria každých 5 sekúnd

// Deklarácie funkcií
void spustiRegulaciu();
void odosliTelemetriu();
void spracujRiadenie(String prijaty_json);
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length);

// ==========================================
// SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  sensors.begin();

  ledcAttach(PELTIER_PIN, PWM_FREQ, PWM_RESOLUTION);
  ledcWrite(PELTIER_PIN, 0); 

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

  // Nastavenie WebSocket klienta
  webSocket.begin(ws_host, ws_port, ws_url);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000); // Pri výpadku sa pokúsi znova pripojiť každých 5s

  Serial.println("WebSocket klient spustený a pripája sa na Flask...");
}

// ==========================================
// MAIN LOOP
// ==========================================
void loop() {
  webSocket.loop(); // Udržiava spojenie a spracováva prichádzajúce dáta

  unsigned long currentMillis = millis();

  // 1. PID Regulácia beží každú 1 sekundu
  if (currentMillis - lastControl >= sampleTimePID) {
    lastControl = currentMillis;
    spustiRegulaciu();
  }

  // 2. Odosielanie telemetrie beží každých 5 sekúnd
  if (currentMillis - lastTelemetry >= sampleTimeWS) {
    lastTelemetry = currentMillis;
    odosliTelemetriu();
  }
}

// ==========================================
// REÁLNY SENZOR -> PID REGULÁCIA (Každú 1s)
// ==========================================
void spustiRegulaciu() {
  // 1. ČÍTANIE HODNÔT
  sensors.requestTemperatures();
  float dallasTemp = sensors.getTempCByIndex(0);
  
  if (dallasTemp == DEVICE_DISCONNECTED_C) {
    Serial.println("[CHYBA] Senzor teploty je odpojený!");
    temperature = 0.0; 
  } else {
    temperature = dallasTemp;
  }

  // 2. PI REGULÁTOR
  if (aktualny_stav == "START") {
    error = -1 * (cielova_teplota - temperature);
    integral += error;

    float maxIntegral = 255.0 / konstant_ki;
    if (integral > maxIntegral) integral = maxIntegral;
    if (integral < 0) integral = 0;

    output = (konstant_kp * error) + (konstant_ki * integral);

    if (output > 255) output = 255;
    if (output < 0) output = 0;

  } else {
    output = 0;
    integral = 0; 
    error = 0;
  }

  ledcWrite(PELTIER_PIN, (int)output);
}

// ==========================================
// ODOSIELANIE TELEMETRIE CEZ WS (Každých 5s)
// ==========================================
void odosliTelemetriu() {
  // Výpis do sériového portu (teraz iba raz za 5s, aby nespamoval konzolu každú sekundu)
  Serial.printf("[STAV: %s] Reálna Temp: %.2f °C | Setpoint: %.1f | Error: %.2f | Výkon PWM: %d\n",
                aktualny_stav.c_str(), temperature, cielova_teplota, error, (int)output);

  if (webSocket.isConnected()) {
    char jsonBuffer[384];
    
    // Protokol Socket.io vyžaduje na začiatku textu prefix 42 a formát ["nazov_udalosti", {objekt}]
    snprintf(jsonBuffer, sizeof(jsonBuffer),
             "42[\"telemetria\",{\"stav_systemu\":\"%s\",\"teplota\":%.2f,\"peltier_pwm\":%d,\"error\":%.2f,\"setpoint\":%.1f,\"kp\":%.1f,\"ki\":%.1f}]",
             aktualny_stav.c_str(), temperature, (int)output, error, cielova_teplota, konstant_kp, konstant_ki);

    webSocket.sendTXT(jsonBuffer);
    Serial.println("-> [WS] Telemetria odoslaná na Flask.");
  } else {
    Serial.println("[WS] Výstraha: Telemetria neodoslaná, WebSocket odpojený!");
  }
}

// ==========================================
// WEBSOCKET UDALOSTI A PRIJÍMANIE SPRÁV
// ==========================================
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Spojenie so serverom prerušené!");
      break;
    case WStype_CONNECTED:
      Serial.printf("[WS] Úspešne pripojené k serveru: %s\n", payload);
      webSocket.sendTXT("40");
      break;
    case WStype_TEXT: {
      String msg = String((char*)payload);
      
      if (msg.startsWith("42") && msg.indexOf("\"riadenie\"") != -1) {
        int jsonStart = msg.indexOf('{');
        if (jsonStart != -1) {
          String kluco_json = msg.substring(jsonStart);
          
          if (kluco_json.endsWith("]")) {
            kluco_json = kluco_json.substring(0, kluco_json.length() - 1);
          }
          spracujRiadenie(kluco_json);
        }
      }
      break;
    }
    default:
      break;
  }
}

// ==========================================
// PARSOVANIE PRICHÁDZAJÚCICH DÁT Z WEBU
// ==========================================
void spracujRiadenie(String prijaty_json) {
  Serial.println("\n<- [Flask WS] Prijaté dáta z webu: " + prijaty_json);

  bool zmena = false;

  int idxPrikaz = prijaty_json.indexOf("\"prikaz\"");
  if (idxPrikaz != -1) {
    int startHladania = prijaty_json.indexOf(":", idxPrikaz);
    int start = prijaty_json.indexOf("\"", startHladania) + 1;
    int koniec = prijaty_json.indexOf("\"", start);
    
    if (start > 0 && koniec > start) {
      aktualny_stav = prijaty_json.substring(start, koniec);
      aktualny_stav.trim(); 
      zmena = true;
    }
  }

  int idxSetpoint = prijaty_json.indexOf("\"setpoint\":");
  if (idxSetpoint != -1) {
    int start = idxSetpoint + 11;
    int koniec = prijaty_json.indexOf(",", start);
    if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
    cielova_teplota = prijaty_json.substring(start, koniec).toFloat();
    zmena = true;
  }

  int idxKp = prijaty_json.indexOf("\"kp\":");
  if (idxKp != -1) {
    int start = idxKp + 5;
    int koniec = prijaty_json.indexOf(",", start);
    if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
    konstant_kp = prijaty_json.substring(start, koniec).toFloat();
    zmena = true;
  }

  int idxKi = prijaty_json.indexOf("\"ki\":");
  if (idxKi != -1) {
    int start = idxKi + 5;
    int koniec = prijaty_json.indexOf(",", start);
    if (koniec == -1) koniec = prijaty_json.indexOf("}", start);
    konstant_ki = prijaty_json.substring(start, koniec).toFloat();
    zmena = true;
  }

  if (zmena) {
    Serial.printf("[UPDATE] Úspešne zmenené -> Stav: %s | Setpoint: %.1f | Kp: %.1f | Ki: %.1f\n", 
                  aktualny_stav.c_str(), cielova_teplota, konstant_kp, konstant_ki);
  }
}