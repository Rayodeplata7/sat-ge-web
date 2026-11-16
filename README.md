# HELIOS-9 // SAT-GEO 4.0 PRO
## Sistema Ciberfísico de Monitoreo Geotécnico y Alerta Temprana en Tiempo Real

Plataforma integral de telemetría geotécnica sobre **ESP32 (`ESP32-D0WD-V3`)** con adquisición de **6 canales a 250 Hz**, validación por checksum **XOR**, servidor local Flask, aplicación nativa **Android Kotlin (USB OTG + Wi-Fi)**, procesamiento **MATLAB** y **Gemelo Digital 3D (WebGL / Three.js + PWA)**.

---

## 🌐 Plataforma Web (GitHub Pages / PWA)
- **URL Pública:** `https://rayodeplata7.github.io/sat-ge-web`
- **Capacidades:**
  - **Gemelo Digital 3D (Three.js):** Nivel freático dinámico, grieta de tracción, muro con contrafuertes, inclinación y desplazamiento del talud en tiempo real.
  - **Doble Tema:** Modo Operador Oscuro (`#030306`) y Modo Claro **ISOPOP** de alto contraste.
  - **Ingesta Multi-Fuente:** Web Serial API directa por USB (`115200 baud`), Wi-Fi AP del ESP32 (`/api/telemetry`), Servidor Local Python (`localhost:5000`) y Simulador Geotécnico (`NORMAL` / `LLUVIA`).
  - **Motor Geomecánico:** Factor de Seguridad (FS) Mohr-Coulomb, Círculo de Mohr dinámico, Mapa GIS (Leaflet) y Osciloscopio en tiempo real.

---

## 📁 Estructura del Repositorio

```text
sat-ge-web/
├── index.html                           # Dashboard Web HELIOS-9 + Gemelo Digital 3D + PWA
├── manifest.json                        # Manifiesto PWA instalable
├── sw.js                                # Service Worker (offline cache)
├── .nojekyll                            # Bypass de Jekyll para GitHub Pages
├── README.md                            # Documentación principal del proyecto
├── sat_geo_android_app_kotlin.zip       # Proyecto completo App Android nativa en Kotlin
│
├── firmware/
│   ├── firmware_esp32_helios/
│   │   └── firmware_esp32_helios.ino    # Firmware oficial ESP32 (Arduino Core v2.x/v3.x, Wi-Fi + USB 115200, XOR)
│   └── main.c                           # Referencia legacy STM32F407VG
│
├── server/
│   └── server.py                        # Backend Flask + lector Serial USB + simulador geotécnico
│
├── matlab/
│   └── proyecto_muestreo_sensores.m     # Script MATLAB de 6 canales y análisis espectral
│
├── documentacion/
│   ├── MEMORIA_TECNICA_DEFINITIVA_SISTEMAS_DIGITALES.pdf
│   ├── DIAGRAMA_CONEXION_PINOUT_HARDWARE.md
│   └── GUIA_SUSTENTACION_PREGUNTAS_TRAMPA_PROFESOR.md
│
├── dataset/
│   ├── telemetria_sat_geo_ensayo_oficial.csv
│   └── telemetria_sat_geo_ensayo_oficial.mat
│
└── img/
    ├── icon-192.png
    └── icon-512.png
```

---

## ⚡ Especificaciones Técnicas del Hardware (ESP32)

| Parámetro | Valor |
| :--- | :--- |
| **Microcontrolador** | ESP32-D0WD-V3 (Dual Core @ 240 MHz, Wi-Fi + UART CP2102) |
| **Frecuencia de Muestreo** | **250.0 Hz** (`Ts = 4.0 ms` por temporizador por hardware) |
| **Protocolo Serial USB** | `115200 baud`, trama `@,00,6,<FSR>,<IR>,<SOIL>,<AX>,<AY>,<AZ>,<XOR>;` |
| **Acelerómetro I2C (ADXL345)** | `SDA → GPIO21`, `SCL → GPIO22`, `VCC → 3.3V`, `GND → GND` |
| **Sensor FSR (Carga)** | `GPIO34` (ADC1) |
| **Sensor IR (Desplazamiento)** | `GPIO35` (ADC1) |
| **Sensor Humedad de Suelo** | `GPIO32` (ADC1) |

---

## 🚀 Cómo ejecutar en local
1. **Hardware:** Flashea `firmware/firmware_esp32_helios/firmware_esp32_helios.ino` desde Arduino IDE (placa ESP32 Dev Module, puerto `COMx` a `115200`).
2. **Servidor Local (opcional para puente HTTP):**
   ```bash
   python server/server.py
   ```
   Luego abre `http://localhost:5000/`.
3. **Conexión directa sin servidor:** Abre `https://rayodeplata7.github.io/sat-ge-web` en Chrome/Edge y pulsa **Conectar USB (Web Serial)**.
