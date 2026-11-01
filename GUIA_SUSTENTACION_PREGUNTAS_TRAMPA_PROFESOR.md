# GUÍA DEFINITIVA DE SUSTENTACIÓN: PREGUNTAS TRAMPA DEL PROFESOR
## Proyecto Final: SAT-GEO 4.0 | Microcontrolador STM32F407VG Discovery (Cortex-M4)

Esta guía contiene las respuestas exactas, técnicas y con rigor de ingeniería a las preguntas que los jurados y profesores de **Sistemas Digitales** hacen para calificar con 5.0/5.0.

---

### PREGUNTA 1: "¿Por qué muestrean a 250 Hz y no a 10 Hz o a 10 kHz?"
- **Respuesta de Nivel Dios:**
  > "Ingeniero, el Teorema de Muestreo de Nyquist-Shannon exige que $f_s \ge 2 f_{max}$. Los fenómenos de colapso geomecánico y micro-vibraciones sísmicas del suelo tienen componentes de frecuencia que llegan hasta los 40–50 Hz. Un muestreo de 10 Hz produciría submuestreo severo (*aliasing*).
  > Por otro lado, muestrear a 10 kHz saturaría innecesariamente el bus serie USART2 a 115200 baudios. A 250 Hz, cada muestra dura exactamente **4.0 ms**. Con una trama de 22 bytes, consumimos aproximadamente 25.3 kbps del ancho de banda disponible (22% del bus USART2), lo que deja al núcleo ARM Cortex-M4 con un 96% de tiempo de CPU libre para el filtrado digital por hardware."

---

### PREGUNTA 2: "¿Cómo configuraron el temporizador TIM2 en el STM32 para lograr exactamente 250 Hz?"
- **Respuesta de Nivel Dios:**
  > "El microcontrolador STM32F407VG tiene el bus APB1 corriendo con el reloj de temporizadores a **84 MHz**. 
  > Para obtener una frecuencia de interrupción de 250 Hz:
  > $$f_{INT} = \frac{f_{TIM}}{(PSC + 1)(ARR + 1)} = \frac{84\,000\,000}{(83 + 1)(3999 + 1)} = \frac{84\,000\,000}{84 \times 4000} = 250.00\text{ Hz}$$
  > Es decir, configuramos el Prescaler $PSC = 83$ y el Auto-Reload Register $ARR = 3999$. La interrupción `TIM2_IRQHandler` se dispara cada 4.00 ms con una precisión de picosegundos dictada por el oscilador de cristal."

---

### PREGUNTA 3: "¿Cómo acondicionaron la señal del sensor de fuerza Tekscan FlexiForce A201?"
- **Respuesta de Nivel Dios:**
  > "El Tekscan A201 es un sensor piezorresistivo cuya resistencia disminuye de manera inversamente proporcional a la fuerza aplicada ($R > 5\text{ M}\Omega$ en reposo hasta $\approx 5\text{ k}\Omega$ a 4.4 N).
  > Implementamos un divisor de tensión con una resistencia de referencia $R_0 = 10\text{ k}\Omega$ conectada a GND y alimentada a $V_{CC} = 3.0\text{ V}$. El voltaje entregado al pin `PA1` del ADC1 es:
  > $$V_{out} = V_{CC} \left( \frac{R_0}{R_0 + R_{sensor}(F)} \right)$$
  > En el firmware linealizamos la respuesta mediante la ecuación de calibración:
  > $$F\text{ (N)} = 0.01467 \cdot (\text{ADC}_{raw} - 65)$$
  > Donde 65 corresponde al offset del umbral de precarga mecánica."

---

### PREGUNTA 4: "¿Por qué el sensor infrarrojo Sharp tiene una zona ciega y cómo la compensaron?"
- **Respuesta de Nivel Dios:**
  > "El Sharp GP2Y0A21YK0F funciona por triangulación óptica PSD (*Position Sensitive Detector*). Por debajo de 4 cm tiene una inversión de pendiente que produce lecturas falsas (ambigüedad óptica).
  > Para solucionarlo:
  > 1. Montamos el sensor físicamente con un espaciador de retroceso de 5 cm respecto a la corona del muro.
  > 2. Aplicamos la curva potencial inversa de calibración en el firmware: $d = 27.86 \cdot V_{sensor}^{-1.15}$.
  > 3. Implementamos un filtro de baseline dinámico en firmware para cancelar la luz solar ambiental."

---

### PREGUNTA 5: "¿Cómo garantizan la integridad de los datos en la transmisión serie?"
- **Respuesta de Nivel Dios:**
  > "Cada paquete transmitido sigue el protocolo industrial:
  > `@,00,2,raw_f,raw_ir,xor;\r\n`
  > Donde `@` es el byte de sincronización de inicio (SOF) y `;` es el fin de trama (EOF). El último campo es un **checksum XOR byte a byte** calculado en hardware por la STM32. Si la aplicación móvil o la estación web reciben un checksum que no coincide exactamente con `raw_f ^ raw_ir`, la muestra se descarta automáticamente, impidiendo falsas alarmas por ruido electromagnético."

---

### PREGUNTA 6: "¿Cómo se calcula el Factor de Seguridad (FS) y qué significa geomecánicamente?"
- **Respuesta de Nivel Dios:**
  > "Aplicamos el Criterio de Rotura de Mohr-Coulomb:
  > $$FS = \frac{\tau_f}{\tau_m} = \frac{c' + (\sigma_n - u)\tan\phi'}{\tau_m}$$
  > - Si $FS > 1.5$: El talud es completamente **Estable** (fase elástica del suelo).
  > - Si $1.0 \le FS < 1.35$: Fase de **Pre-alerta / Deformación plástica secundaria**.
  > - Si $FS < 1.0$: **Falla inminente**. Las fuerzas desestabilizadoras superan la resistencia al corte del suelo y el sistema activa la sirena acústica y la vibración háptica en el celular."
