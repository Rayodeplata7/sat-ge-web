# DIAGRAMA DE CONEXIÓN FÍSICA & PINOUT OFICIAL
## Sistema Digital Embebido SAT-GEO 4.0 | STM32F407VG Discovery

Este documento especifica el alambrado exacto para conectar los sensores físicos y el módulo de comunicación a la tarjeta **STM32F407VG Discovery**.

---

## 📌 1. Mapa de Pines del Microcontrolador

| Pin STM32F407 | Función de Hardware | Conexión Física | Descripción Técnica |
| :--- | :--- | :--- | :--- |
| **PA1** | `ADC1_IN1` | Salida Sensor Tekscan A201 | Canal analógico 1 (0 – 3.0 V, 12 bits) |
| **PA4** | `ADC1_IN4` | Salida Vo Sensor Sharp IR | Canal analógico 4 (0 – 3.0 V, 12 bits) |
| **PA2** | `USART2_TX` | RX de Interfaz Serie / Bluetooth | Transmisión serie a 115200 baudios |
| **PA3** | `USART2_RX` | TX de Interfaz Serie / Bluetooth | Recepción serie a 115200 baudios |
| **VDD / 3V** | Alimentación $3.0\text{ V}$ | Terminal VCC de Sensores | Voltaje de referencia analógico |
| **GND** | Tierra Común | Terminal GND de Sensores | Referencia de 0V común de todo el circuito |

---

## ⚡ 2. Diagrama Esquemático del Sensor Tekscan FlexiForce A201

El sensor Tekscan es de 2 terminales y no tiene polaridad:

```
  [ VDD 3.0V (STM32) ]
          │
          │
      ┌───┴───┐
      │ SENSOR│  Tekscan FlexiForce A201
      │ A201  │  (Resistencia variable con la fuerza)
      └───┬───┘
          │
          ├─────────────────────► A Pin PA1 (ADC1_IN1 de STM32)
          │
      ┌───┴───┐
      │ R0    │  Resistencia de carga: 10 kΩ (Marrón - Negro - Naranja - Dorado)
      │ 10 kΩ │
      └───┬───┘
          │
          ▼
     [ GND (STM32) ]
```

---

## 👁️ 3. Diagrama Esquemático del Sensor Óptico Sharp GP2Y0A21YK0F

El cable conector del sensor Sharp tiene 3 pines:

| Cable Sharp | Pin en el Sensor | Conexión a STM32F407 |
| :--- | :--- | :--- |
| **Cable Rojo** | `Vcc` ($4.5 - 5.0\text{ V}$) | Pin `5V` de la Discovery |
| **Cable Negro** | `GND` | Pin `GND` de la Discovery |
| **Cable Amarillo / Blanco**| `Vo` (Señal de salida) | Pin **PA4** (`ADC1_IN4`) de la Discovery |

---

## 📡 4. Diagrama de Enlace Inalámbrico / Serie (USART2)

Si se conecta un módulo Bluetooth (HC-05 / HC-06) o interfaz serie:

- **TX del Módulo** $\to$ Pin **PA3** (`USART2_RX`) de la STM32.
- **RX del Módulo** $\to$ Pin **PA2** (`USART2_TX`) de la STM32 (usar divisor de tensión $1\text{ k}\Omega / 2\text{ k}\Omega$ si el módulo es de 3.3V).
- **VCC del Módulo** $\to$ Pin `5V` o `3V` según especificación.
- **GND del Módulo** $\to$ Pin `GND` común.

---

## ✅ Lista de Verificación antes de Energizar:
1. Verificar que la resistencia de $10\text{ k}\Omega$ esté conectada firmemente entre `PA1` y `GND`.
2. Verificar que el cable micro-USB esté conectado al puerto **ST-LINK** (puerto USB superior) para alimentación y programación.
3. Comprobar que el LED verde de encendido `PWR` en la tarjeta Discovery esté iluminado fijo.
