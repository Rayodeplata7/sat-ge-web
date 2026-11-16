/**
 * ============================================================================
 * PROYECTO: HELIOS-9 // GEO-LATTICE 4.0 PRO - ESTACIÓN CIBERFÍSICA IOT
 * AUTOR: Eric Piraquive — PiraquivePropTech (Persona Natural Art. 437 E.T.)
 * TARGET: ESP32 Dual-Core Xtensa LX6 @ 240 MHz
 * PROTOCOLO: SAT-GEO v4.0 (115200 Baudios USB-UART + Web Server WiFi JSON)
 * LIBRERÍAS: 100% NATIVAS DE ESP32 (Wire.h, WiFi.h, WebServer.h)
 * ============================================================================
 * 
 * MAPEO DE PINES (ASIGNACIÓN EXCLUSIVA ADC1 PARA COMPATIBILIDAD WI-FI TOTAL):
 *   - GPIO21 (SDA)  : Bus I2C Datos - ADXL345 (Acelerómetro / Inclinómetro)
 *   - GPIO22 (SCL)  : Bus I2C Reloj - ADXL345 (Acelerómetro / Inclinómetro)
 *   - GPIO34 (ADC1) : ADC1_CH6 - FSR-406 Sensor de Presión Activa / Empuje
 *   - GPIO35 (ADC1) : ADC1_CH7 - Sensor Óptico IR P/N 1102 (Grieta Coronal)
 *   - GPIO32 (ADC1) : ADC1_CH4 - Sonda Higrométrica de Suelo LM393 (Humedad W%)
 *   - GPIO2  (LED)  : LED Onboard Azul (Heartbeat de adquisición a 250 Hz)
 * 
 * TRAMA INDUSTRIAL SERIAL (USB-UART):
 *   @,00,6,<RAW_FSR>,<RAW_IR>,<RAW_SOIL>,<ACC_X>,<ACC_Y>,<ACC_Z>,<XOR_HEX>;\r\n
 * ============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>

// --- CONFIGURACIÓN DE RED WI-FI (MODO AP AUTOGESTIONADO) ---
const char* AP_SSID = "HELIOS-9-MISSION-CONTROL";
const char* AP_PASS = "piraquive2026"; // Clave de 8 caracteres o más

WebServer server(80);

// --- DIRECCIÓN Y REGISTROS ADXL345 ---
#define ADXL345_I2C_ADDR 0x53
#define ADXL345_DEVID_REG 0x00
#define ADXL345_POWER_CTL 0x2D
#define ADXL345_DATA_FORMAT 0x31
#define ADXL345_DATAX0 0x32

// --- ASIGNACIÓN DE PINES (ADC1 COMPATIBLE CON WI-FI SIMULTÁNEO) ---
#define PIN_FSR_ADC    34 // GPIO34 (ADC1_CH6) - Interlink FSR-406 + 10k pull-down
#define PIN_IR_ADC     35 // GPIO35 (ADC1_CH7) - Óptico IR P/N 1102
#define PIN_SOIL_ADC   32 // GPIO32 (ADC1_CH4) - Sonda Suelo LM393 (AO)
#define PIN_LED_STATUS 2  // LED Azul de la placa

// --- VARIABLES GLOBALES DE TELEMETRÍA (250 HZ) ---
volatile uint32_t raw_fsr = 0;
volatile uint32_t raw_ir = 0;
volatile uint32_t raw_soil = 0;
int16_t acc_x = 0;
int16_t acc_y = 0;
int16_t acc_z = 256;

hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;
volatile bool sampleFlag = false;

// Buffer de transmisión
char packetBuffer[128];
uint32_t sampleCounter = 0;

// --- INTERRUPCIÓN DEL TEMPORIZADOR DE HARDWARE (CADA 4.0 MS = 250 HZ) ---
void IRAM_ATTR onTimer() {
  portENTER_CRITICAL_ISR(&timerMux);
  sampleFlag = true;
  portEXIT_CRITICAL_ISR(&timerMux);
}

// --- CHECKSUM XOR INDUSTRIAL ---
uint8_t calculateXOR(const char* data) {
  uint8_t xorVal = 0;
  while (*data) {
    xorVal ^= (uint8_t)(*data);
    data++;
  }
  return xorVal;
}

// --- INICIALIZACIÓN ADXL345 ---
bool initADXL345() {
  Wire.begin(21, 22, 400000); // SDA=21, SCL=22, 400 kHz Fast Mode
  
  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(ADXL345_DEVID_REG);
  if (Wire.endTransmission() != 0) return false;

  Wire.requestFrom(ADXL345_I2C_ADDR, 1);
  if (!Wire.available()) return false;
  uint8_t devId = Wire.read();
  if (devId != 0xE5) return false;

  // Rango +-4g con Full Resolution
  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(ADXL345_DATA_FORMAT);
  Wire.write(0x09);
  Wire.endTransmission();

  // Activar modo de medición continua
  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(ADXL345_POWER_CTL);
  Wire.write(0x08);
  Wire.endTransmission();

  return true;
}

// --- LECTURA EN RÁFAGA ADXL345 (6 BYTES) ---
void readADXL345() {
  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(ADXL345_DATAX0);
  if (Wire.endTransmission() == 0) {
    Wire.requestFrom(ADXL345_I2C_ADDR, 6);
    if (Wire.available() >= 6) {
      uint8_t x0 = Wire.read(); uint8_t x1 = Wire.read();
      uint8_t y0 = Wire.read(); uint8_t y1 = Wire.read();
      uint8_t z0 = Wire.read(); uint8_t z1 = Wire.read();
      acc_x = (int16_t)((x1 << 8) | x0);
      acc_y = (int16_t)((y1 << 8) | y0);
      acc_z = (int16_t)((z1 << 8) | z0);
      return;
    }
  }
  // Cero explícito si el ADXL345 está desconectado o sin respuesta I2C (cero datos inventados)
  acc_x = 0;
  acc_y = 0;
  acc_z = 0;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_STATUS, OUTPUT);
  digitalWrite(PIN_LED_STATUS, LOW);

  // Configuración ADC1 a 12 bits (0 a 4095) y rango 0 a 3.3V
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  Serial.println("\n=======================================================");
  Serial.println("  HELIOS-9 // GEO-LATTICE 4.0 PRO - INICIALIZANDO ESP32");
  Serial.println("  PiraquivePropTech - Eric Piraquive (Art. 437 E.T.)");
  Serial.println("=======================================================");

  // 1. Inicializar I2C para ADXL345
  if (initADXL345()) {
    Serial.println("[OK] Sensor ADXL345 detectado e inicializado en I2C (0x53).");
  } else {
    Serial.println("[WARN] ADXL345 no respondio en 0x53. Verifique SDA(GPIO21), SCL(GPIO22).");
  }

  // 2. Levantar Punto de Acceso Wi-Fi Autogestionado
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  IPAddress myIP = WiFi.softAPIP();
  Serial.print("[OK] Red Wi-Fi AP levantada: "); Serial.println(AP_SSID);
  Serial.print("[OK] Servidor IP: http://"); Serial.println(myIP);

  // 3. Servidor Web HTTP JSON (/api/telemetry) con cabeceras CORS libres
  server.on("/api/telemetry", HTTP_OPTIONS, []() {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
    server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
    server.send(204);
  });

  server.on("/api/telemetry", HTTP_GET, []() {
    float f = (raw_fsr > 65) ? fminf(4.4f, (float)(raw_fsr - 65) * 0.01467f) : 0.0f;
    float dist_cm = fmaxf(0.2f, 5.0f - ((float)raw_ir / 4095.0f) * 4.6f);
    float d = fmaxf(0.0f, (5.0f - dist_cm) * 10.0f);
    float h = fmaxf(5.0f, fminf(100.0f, ((3800.0f - (float)raw_soil) / 2600.0f) * 100.0f));
    float az_safe = fabsf((float)acc_z) > 1.0f ? fabsf((float)acc_z) : 1.0f;
    float tilt = atan2f(sqrtf((float)acc_x * acc_x + (float)acc_y * acc_y), az_safe) * (180.0f / 3.1415926f);
    
    char json[320];
    snprintf(json, sizeof(json),
      "{\"raw_fsr\":%lu,\"raw_ir\":%lu,\"raw_soil\":%lu,\"acc_x\":%d,\"acc_y\":%d,\"acc_z\":%d,\"force\":%.2f,\"disp\":%.2f,\"hum\":%.1f,\"tilt\":%.2f,\"samples\":%u}",
      (unsigned long)raw_fsr, (unsigned long)raw_ir, (unsigned long)raw_soil,
      (int)acc_x, (int)acc_y, (int)acc_z,
      f, d, h, tilt, sampleCounter
    );
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(200, "application/json", json);
  });
  
  server.begin();

  // 4. Temporizador de Hardware para Muestreo a 250.0 Hz (cada 4.0 ms)
#if defined(ESP_ARDUINO_VERSION) && ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &onTimer);
  timerAlarm(timer, 4000, true, 0);
#else
  timer = timerBegin(0, 80, true);
  timerAttachInterrupt(timer, &onTimer, true);
  timerAlarmWrite(timer, 4000, true);
  timerAlarmEnable(timer);
#endif

  digitalWrite(PIN_LED_STATUS, HIGH);
  Serial.println("[OK] Adquisicion a 250.0 Hz sincronizada por Timer0 de hardware.");
  Serial.println(">> SISTEMA LISTO TRANSMITIENDO TRAMAS SAT-GEO...");
}

void loop() {
  server.handleClient();

  if (sampleFlag) {
    portENTER_CRITICAL(&timerMux);
    sampleFlag = false;
    portEXIT_CRITICAL(&timerMux);

    sampleCounter++;

    // 1. Muestreo de Sensores en ADC1
    raw_fsr  = analogRead(PIN_FSR_ADC);
    raw_ir   = analogRead(PIN_IR_ADC);
    raw_soil = analogRead(PIN_SOIL_ADC);

    // 2. Lectura I2C del ADXL345
    readADXL345();

    // 3. Armado de Trama Industrial
    char payload[96];
    snprintf(payload, sizeof(payload), "00,6,%lu,%lu,%lu,%d,%d,%d",
      (unsigned long)raw_fsr,
      (unsigned long)raw_ir,
      (unsigned long)raw_soil,
      (int)acc_x, (int)acc_y, (int)acc_z
    );

    uint8_t xorChk = calculateXOR(payload);
    snprintf(packetBuffer, sizeof(packetBuffer), "@,%s,%02X;\r\n", payload, xorChk);

    // 4. Transmisión Serial no bloqueante (50 Hz @ 115200 baud, muestreo interno a 250 Hz)
    if (sampleCounter % 5 == 0) {
      Serial.print(packetBuffer);
    }

    // Toggle Heartbeat LED
    if (sampleCounter % 125 == 0) {
      digitalWrite(PIN_LED_STATUS, !digitalRead(PIN_LED_STATUS));
    }
  }
}
