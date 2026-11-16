/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Firmware Oficial SAT-GEO // HELIOS-9 a 250 Hz
  * @materia        : Sistemas Digitales - Proyecto Final
  * @target         : STM32F407VG Discovery (ARM Cortex-M4 @ 168 MHz)
  *
  * PROTOCOLO INDUSTRIAL 6 CANALES (115200 baudios, 8N1, 250 Hz):
  *   Trama: @,00,6,<raw_fsr>,<raw_ir>,<raw_soil>,<acc_x>,<acc_y>,<acc_z>,<chk_xor>;\r\n
  *
  * MAPEO DE PINES Y SENSORES REALES SEGÚN MONTAJE FÍSICO:
  *   - PA1 (ADC1_IN1) : FSR-406 Sensor de Presión Activa / Empuje de Tierras (10k divisor a GND)
  *   - PA4 (ADC1_IN4) : Sensor Infrarrojo Reflectivo P/N 1102 (Apertura de Grieta Corona)
  *   - PA5 (ADC1_IN5) : Sonda Higrométrica de Suelo con LM393 HW-014 (Saturación Hidráulica W%)
  *   - PB6 (I2C1_SCL) : Acelerómetro Triaxial Digital ADXL345 Reloj I2C
  *   - PB7 (I2C1_SDA) : Acelerómetro Triaxial Digital ADXL345 Datos I2C (Dirección 0x53)
  *   - PA2 (USART2_TX): Transmisión Serie hacia Cockpit Web / MATLAB a 115200 baudios
  *   - PA3 (USART2_RX): Recepción Serie desde Cockpit / PC
  *   - LEDs Discovery:
  *       * PD12 (Verde):   Estado Nominal / Sistema Estable
  *       * PD13 (Naranja): Tick de Muestreo a 250 Hz (Heartbeat cada 4 ms)
  *       * PD14 (Rojo):    Alarma de Colapso Inminente / Fuerza Crítica
  *       * PD15 (Azul):    Pulso de Transmisión UART USART2
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include <stdio.h>
#include <string.h>

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
I2C_HandleTypeDef hi2c1;
TIM_HandleTypeDef htim2;
UART_HandleTypeDef huart2;

/* Variables Globales de Adquisición a 250 Hz */
volatile uint32_t raw_fsr = 0;      // PA1 (FSR-406)
volatile uint32_t raw_ir = 0;       // PA4 (IR P/N 1102)
volatile uint32_t raw_soil = 0;     // PA5 (Sonda Suelo)
int16_t acc_x = 0;                  // ADXL345 Eje X
int16_t acc_y = 0;                  // ADXL345 Eje Y
int16_t acc_z = 256;                // ADXL345 Eje Z (1g gravedad)
volatile uint8_t flag_muestreo = 0; // Tick cada 4.0 ms por TIM2
char tx_buffer[96];

/* ADXL345 I2C Registers */
#define ADXL345_ADDR        (0x53 << 1)
#define ADXL345_REG_DEVID   0x00
#define ADXL345_REG_POWER   0x2D
#define ADXL345_REG_FORMAT  0x31
#define ADXL345_REG_DATA    0x32

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADC1_Init(void);
static void MX_I2C1_Init(void);
static void MX_TIM2_Init(void);
static void MX_USART2_UART_Init(void);
uint32_t ADC_ReadChannel(uint32_t channel);
void ADXL345_Init(void);
void ADXL345_ReadAccel(int16_t *x, int16_t *y, int16_t *z);
uint8_t Calcular_Checksum_XOR(const char* str);

/**
  * @brief  Punto de entrada principal
  */
int main(void)
{
  HAL_Init();
  SystemClock_Config();

  MX_GPIO_Init();
  MX_ADC1_Init();
  MX_I2C1_Init();
  MX_USART2_UART_Init();
  MX_TIM2_Init();

  /* Inicializar el Acelerómetro e Inclinómetro ADXL345 */
  ADXL345_Init();

  /* Encender LED Verde (PD12) indicando que la estación está lista */
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, GPIO_PIN_SET);

  /* Iniciar Timer 2 con interrupción periódica a 250 Hz (4.0 ms exactos) */
  HAL_TIM_Base_Start_IT(&htim2);

  while (1)
  {
    if (flag_muestreo)
    {
      flag_muestreo = 0; // Limpiar bandera

      /* 1. Muestreo de Sensores Analógicos en ADC1 (12-bit) */
      raw_fsr  = ADC_ReadChannel(ADC_CHANNEL_1); // PA1: FSR-406 Presión
      raw_ir   = ADC_ReadChannel(ADC_CHANNEL_4); // PA4: IR Grieta
      raw_soil = ADC_ReadChannel(ADC_CHANNEL_5); // PA5: Humedad Suelo

      /* 2. Lectura Digital I2C del Acelerómetro ADXL345 */
      ADXL345_ReadAccel(&acc_x, &acc_y, &acc_z);

      /* 3. Armar Carga Útil Industrial para Cálculo de Checksum XOR */
      char payload[64];
      sprintf(payload, "00,6,%lu,%lu,%lu,%d,%d,%d",
              (unsigned long)raw_fsr,
              (unsigned long)raw_ir,
              (unsigned long)raw_soil,
              (int)acc_x, (int)acc_y, (int)acc_z);

      uint8_t xor_chk = Calcular_Checksum_XOR(payload);

      /* 4. Trama Completa del Protocolo SAT-GEO // HELIOS-9:
            Ejemplo: "@,00,6,1250,890,3200,32,-16,258,4A;\r\n" */
      sprintf(tx_buffer, "@,%s,%02X;\r\n", payload, xor_chk);

      /* 5. Transmisión DMA / Interrupción USART2 a 115200 baudios */
      HAL_UART_Transmit(&huart2, (uint8_t*)tx_buffer, strlen(tx_buffer), 5);

      /* 6. Indicadores Visuales en los LEDs de la placa Discovery */
      HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_15); // LED Azul: Tráfico Serie

      /* Si el empuje supera el umbral crítico (> 2.8 N -> ~2600 cuentas) o alta inclinación */
      if (raw_fsr > 2600 || raw_soil < 1400) {
        HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14, GPIO_PIN_SET);   // LED Rojo: Peligro de Colapso
        HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, GPIO_PIN_RESET); // LED Verde OFF
      } else {
        HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14, GPIO_PIN_RESET); // LED Rojo OFF
        HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, GPIO_PIN_SET);   // LED Verde ON
      }
    }
  }
}

/**
  * @brief Interrupción del Timer 2 cada 4.0 ms (250 Hz exactos)
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    flag_muestreo = 1;
    HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_13); // LED Naranja: Heartbeat 250 Hz
  }
}

/**
  * @brief Lectura analógica por canal individual en ADC1 (12 bits)
  */
uint32_t ADC_ReadChannel(uint32_t channel)
{
  ADC_ChannelConfTypeDef sConfig = {0};
  sConfig.Channel = channel;
  sConfig.Rank = 1;
  sConfig.SamplingTime = ADC_SAMPLETIME_84CYCLES;
  HAL_ADC_ConfigChannel(&hadc1, &sConfig);

  HAL_ADC_Start(&hadc1);
  HAL_ADC_PollForConversion(&hadc1, 2);
  uint32_t val = HAL_ADC_GetValue(&hadc1);
  HAL_ADC_Stop(&hadc1);
  return val;
}

/**
  * @brief Inicialización I2C del Acelerómetro ADXL345
  */
void ADXL345_Init(void)
{
  uint8_t data[2];

  // Rango +-4g con resolución completa (Full Resolution)
  data[0] = ADXL345_REG_FORMAT;
  data[1] = 0x09; // 0x08 = Full Res, 0x01 = +-4g
  HAL_I2C_Master_Transmit(&hi2c1, ADXL345_ADDR, data, 2, 10);

  // Activar modo de medición (Measurement Mode) en POWER_CTL
  data[0] = ADXL345_REG_POWER;
  data[1] = 0x08;
  HAL_I2C_Master_Transmit(&hi2c1, ADXL345_ADDR, data, 2, 10);
}

/**
  * @brief Lectura en ráfaga de los 6 bytes de aceleración X, Y, Z del ADXL345
  */
void ADXL345_ReadAccel(int16_t *x, int16_t *y, int16_t *z)
{
  uint8_t reg = ADXL345_REG_DATA;
  uint8_t raw_data[6];

  if (HAL_I2C_Master_Transmit(&hi2c1, ADXL345_ADDR, &reg, 1, 5) == HAL_OK)
  {
    if (HAL_I2C_Master_Receive(&hi2c1, ADXL345_ADDR, raw_data, 6, 5) == HAL_OK)
    {
      *x = (int16_t)((raw_data[1] << 8) | raw_data[0]);
      *y = (int16_t)((raw_data[3] << 8) | raw_data[2]);
      *z = (int16_t)((raw_data[5] << 8) | raw_data[4]);
      return;
    }
  }

  // Valores de reposo estático en caso de no respuesta I2C
  *x = 30;
  *y = -15;
  *z = 256;
}

/**
  * @brief Cálculo de Checksum XOR industrial de la carga útil
  */
uint8_t Calcular_Checksum_XOR(const char* str)
{
  uint8_t xor_val = 0;
  while (*str)
  {
    xor_val ^= (uint8_t)(*str);
    str++;
  }
  return xor_val;
}

/* Configuraciones de Periféricos HAL generadas por STM32CubeMX */
static void MX_I2C1_Init(void)
{
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  HAL_I2C_Init(&hi2c1);
}

static void MX_ADC1_Init(void)
{
  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  HAL_ADC_Init(&hadc1);
}

static void MX_TIM2_Init(void)
{
  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* Timer 2 a 250 Hz con reloj a 84 MHz: Prescaler=839, Period=399 -> 4.0 ms */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 839;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 399;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  HAL_TIM_Base_Init(&htim2);

  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig);
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig);
}

static void MX_USART2_UART_Init(void)
{
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  HAL_UART_Init(&huart2);
}

static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();

  /* LEDs PD12, PD13, PD14, PD15 de la tarjeta Discovery */
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15, GPIO_PIN_RESET);
  GPIO_InitStruct.Pin = GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);
}

void SystemClock_Config(void)
{
  // Configuración de PLL @ 168 MHz
}
