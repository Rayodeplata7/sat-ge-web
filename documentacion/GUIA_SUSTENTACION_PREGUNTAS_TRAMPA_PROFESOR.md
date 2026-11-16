# GUÍA DE SUSTENTACIÓN: PREGUNTAS TRAMPA DE SISTEMAS DIGITALES
**Proyecto:** HELIOS-9 // SAT-GEO 4.0 PRO — Estación Ciberfísica ESP32 (`ESP32-D0WD-V3`)

---

### Pregunta 1: "¿Por qué aseguran muestreo determinístico a 250 Hz si el ESP32 también atiende Wi-Fi y HTTP?"
* **Respuesta técnica:**
  El ESP32 es **Dual-Core (Xtensa LX6 @ 240 MHz)**:
  1. El temporizador por hardware (`hw_timer_t`, `timerBegin(1000000)` en Core v3.x / `timerBegin(0, 80, true)` en v2.x) dispara una interrupción `IRAM_ATTR onTimer()` exactamente cada **`4000 µs` (`Ts = 4.0 ms`, `fs = 250.0 Hz`)** activando la bandera atómica `volatile bool sampleReady`.
  2. La adquisición de los 6 canales y transmisión serial (`115200 baud`) se ejecutan sincronizadas por esa bandera, mientras la pila Wi-Fi / `WebServer` atiende peticiones `/api/telemetry` de forma no bloqueante.

---

### Pregunta 2: "¿Por qué conectaron los sensores analógicos exclusivamente a GPIO34, GPIO35 y GPIO32?"
* **Respuesta técnica:**
  En el ESP32 existen dos convertidores SAR de 12 bits (`0..4095`): **ADC1** y **ADC2**.
  Cuando el radio **Wi-Fi está activo**, el driver RF del ESP32 reserva el controlador **ADC2**, haciendo que cualquier lectura en pines ADC2 falle o devuelva ruido.
  Por eso se asignaron únicamente canales de **ADC1**:
  - `GPIO34` (`ADC1_CH6`) → FSR-406 (empuje).
  - `GPIO35` (`ADC1_CH7`) → Sensor óptico IR P/N 1102 (grieta coronal).
  - `GPIO32` (`ADC1_CH4`) → Sonda de humedad de suelo LM393.

---

### Pregunta 3: "¿Por qué usan un ADXL345 por I2C si ya miden fuerza y desplazamiento?"
* **Respuesta técnica:**
  El desplazamiento superficial (IR) y el empuje (FSR) no distinguen por sí solos si el muro está rotando o volcando. El **ADXL345** conectado por I2C (`GPIO21 SDA`, `GPIO22 SCL` a `400 kHz`, dirección `0x53`) entrega aceleración triaxial (`acc_x, acc_y, acc_z`, escala `256 LSB/g`), con lo cual se calcula el ángulo de inclinación real del muro mediante `atan2(hypot(ax, ay), |az|)` y la componente de vibración sísmica vertical.

---

### Pregunta 4: "¿Cómo garantizan que una trama corrupta por ruido eléctrico en USB no dispare una falsa alarma de colapso?"
* **Respuesta técnica:**
  Cada trama serial cumple el protocolo estricto:
  `@,00,6,<RAW_FSR>,<RAW_IR>,<RAW_SOIL>,<ACC_X>,<ACC_Y>,<ACC_Z>,<XOR_HEX>;\r\n`
  1. El ESP32 calcula el **checksum XOR** byte a byte sobre el payload completo (`00,6,...`) y lo adjunta en hexadecimal (`%02X`).
  2. Tanto el **Dashboard Web (`index.html`)**, la **App Android (`UsbSerialService.kt`)**, el **Servidor Flask (`server.py`)** como **MATLAB (`proyecto_muestreo_sensores.m`)** recalculan el XOR antes de aceptar cualquier muestra; si no coincide, la trama se descarta automáticamente.

---

### Pregunta 5: "¿Cómo se traduce la lectura de sensores al Factor de Seguridad (FS) geotécnico?"
* **Respuesta técnica:**
  El modelo geotécnico **Mohr-Coulomb** calcula la resistencia al corte disponible frente al esfuerzo actuante considerando:
  - Saturación por humedad del suelo (`W%` desde `GPIO32`), que incrementa la presión de poros `u` y reduce el esfuerzo efectivo normal (`σ' = σ - u`).
  - Empuje lateral medido por el FSR-406 (`GPIO34`, `0..4.4 N`) y momento flector (`M = 0.88 * F`).
  - Desplazamiento de grieta coronal IR (`GPIO35`, `0..50 mm`) e inclinación/vibración del ADXL345 (`GPIO21/22`).
  - Umbrales operativos: **`FS >= 1.35` Seguro**, **`1.0 <= FS < 1.35` Precaución**, **`FS < 1.0` Alerta Crítica de Colapso**.
