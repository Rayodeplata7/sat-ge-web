# DIAGRAMA DE CONEXIÓN Y PINOUT HARDWARE — HELIOS-9 // SAT-GEO 4.0 PRO
**Microcontrolador:** ESP32-D0WD-V3 (Dual-Core Xtensa LX6 @ 240 MHz)
**Puente USB-UART:** Silicon Labs CP2102 (`115200 baud`, puerto Windows `COM17`)
**Alimentación de Referencia ADC:** `3.3 V` (exclusivamente pines **ADC1** para compatibilidad total con Wi-Fi)

---

## 1. Mapa de Pines Oficial (ESP32 DevKit)

| Sensor / Periférico | Pin ESP32 | Canal / Bus | Función en el Sistema |
| :--- | :--- | :--- | :--- |
| **Interlink FSR-406** | `GPIO34` | `ADC1_CH6` (solo entrada) | Fuerza activa / empuje sobre muro de contención (`0 – 4.4 N`) |
| **Óptico IR P/N 1102** | `GPIO35` | `ADC1_CH7` (solo entrada) | Desplazamiento de grieta coronal (`0 – 50 mm`) |
| **Sonda Suelo LM393 (AO)** | `GPIO32` | `ADC1_CH4` | Humedad gravimétrica / saturación de poro (`5% – 100%`) |
| **ADXL345 SDA** | `GPIO21` | `I2C SDA` (`400 kHz`) | Inclinómetro triaxial (dirección `0x53`) |
| **ADXL345 SCL** | `GPIO22` | `I2C SCL` (`400 kHz`) | Reloj I2C del acelerómetro ADXL345 |
| **LED Heartbeat** | `GPIO2` | Salida Digital | Parpadeo de muestreo activo a `250 Hz` |

> **Nota crítica de diseño:** No usar pines de `ADC2` (`GPIO0, 2, 4, 12..15, 25..27`) para sensores analógicos porque el controlador Wi-Fi del ESP32 bloquea `ADC2` cuando el Access Point está encendido.

---

## 2. Esquema de Alambrado por Sensor

### A. Sensor de Fuerza FSR-406 (`GPIO34`)
Divisor de tensión con resistencia pull-down `R_0 = 10 kΩ`:
```text
3.3V ────[ FSR-406 ]────┬────► GPIO34 (ADC1_CH6)
                        │
                     [10 kΩ]
                        │
                       GND
```

### B. Sensor Óptico IR P/N 1102 (`GPIO35`)
```text
VIN (3.3V o 5V según módulo) ──► VCC
GND                          ──► GND
VOUT (Señal analógica)       ──► GPIO35 (ADC1_CH7)
```

### C. Sonda Higrométrica de Suelo LM393 (`GPIO32`)
```text
3.3V ──► VCC
GND  ──► GND
AO   ──► GPIO32 (ADC1_CH4)  (usar salida analógica AO, no DO)
```

### D. Acelerómetro / Inclinómetro ADXL345 (`GPIO21` / `GPIO22`)
```text
3.3V ──► VCC
3.3V ──► CS   (obligatorio a 3.3V para activar modo I2C)
GND  ──► GND
GND  ──► SDO  (fija dirección I2C en 0x53)
GPIO21 ──► SDA
GPIO22 ──► SCL
```

---

## 3. Enlace de Telemetría y Verificación
1. **USB-UART / OTG (`115200 baud`, 8-N-1):**
   `@,00,6,<RAW_FSR>,<RAW_IR>,<RAW_SOIL>,<ACC_X>,<ACC_Y>,<ACC_Z>,<XOR_HEX>;\r\n`
2. **Wi-Fi SoftAP Local:**
   - Red: `HELIOS-9-MISSION-CONTROL`
   - Endpoint JSON: `http://192.168.4.1/api/telemetry`
3. **Checklist Pre-Energización:**
   - Verificar que `CS` del ADXL345 esté en `3.3 V` y `SDO` en `GND`.
   - Confirmar que ninguna entrada a los pines GPIO supere `3.3 V`.
   - Cerrar el Monitor Serie de Arduino IDE antes de conectar el Dashboard Web (`Web Serial`) o `server/server.py` al puerto `COM17`.
