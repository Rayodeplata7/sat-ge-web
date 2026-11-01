/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Firmware Oficial de Adquisición a 250 Hz para STM32F407VG Discovery
  * @materia        : Sistemas Digitales - Proyecto Final
  * @target         : STM32F407VG (ARM Cortex-M4 @ 168 MHz)
  *
  * PROTOCOLO DE TRANSMISIÓN SERIAL INDUSTRIAL (115200 baudios, 8N1, 250 Hz):
  *   Trama: @,00,2,<raw_ch1_fuerza>,<raw_ch2_infrarrojo>,<checksum_xor>;\r\n
  *
  * MAPEO DE PINES Y SENSORES SEGÚN DATASHEETS OFICIALES:
  *   - PA1 (ADC1_IN1): Sensor de Fuerza Tekscan FlexiForce A201 (Divisor 10k a GND)
  *   - PA4 (ADC1_IN4): Sensor Óptico Infrarrojo de Proximidad (0 a 5.0 cm)
  *   - PA2 (USART2_TX): Transmisión serie hacia PC / MATLAB a 115200 baudios
  *   - PA3 (USART2_RX): Recepción serie desde PC
  *   - LEDs Discovery:
  *       * PD12 (Verde):   Sistema Listo / Estado Normal
  *       * PD13 (Naranja): Tick de Muestreo a 250 Hz (Heartbeat cada 4 ms)
  *       * PD14 (Rojo):    Alarma de Fuerza Crítica / Prensado Máximo
  *       * PD15 (Azul):    Latido de Transmisión UART
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include <stdio.h>
#include <string.h>

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
TIM_HandleTypeDef htim2;
UART_HandleTypeDef huart2;

/* Variables Globales de Adquisición a 250 Hz */
volatile uint32_t raw_fuerza = 0;   // PA1 (ADC1_IN1)
volatile uint32_t raw_ir = 0;       // PA4 (ADC1_IN4)
volatile uint8_t flag_muestreo = 0; // Se activa cada 4 ms por TIM2
char tx_buffer[64];

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADC1_Init(void);
static void MX_TIM2_Init(void);
static void MX_USART2_UART_Init(void);
uint32_t ADC_ReadChannel(uint32_t channel);
uint8_t Calcular_Checksum_XOR(const char* str);

/**
  * @brief  Punto de entrada principal
  */
int main(void)
{
  /* Inicialización de la biblioteca HAL */
  HAL_Init();

  /* Configuración del reloj del sistema a 168 MHz */
  SystemClock_Config();

  /* Inicialización de periféricos configurados */
  MX_GPIO_Init();
  MX_ADC1_Init();
  MX_USART2_UART_Init();
  MX_TIM2_Init();

  /* Encender LED Verde (PD12) indicando que el sistema está listo */
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, GPIO_PIN_SET);

  /* Iniciar Timer 2 con interrupción a 250 Hz (cada 4.0 ms) */
  HAL_TIM_Base_Start_IT(&htim2);

  while (1)
  {
    if (flag_muestreo)
    {
      flag_muestreo = 0; // Limpiar bandera de muestreo

      /* 1. Muestreo de Canal 1: PA1 (FlexiForce Fuerza) */
      raw_fuerza = ADC_ReadChannel(ADC_CHANNEL_1);

      /* 2. Muestreo de Canal 2: PA4 (Infrarrojo Proximidad) */
      raw_ir = ADC_ReadChannel(ADC_CHANNEL_4);

      /* 3. Armar pre-trama para cálculo del Checksum XOR */
      char payload[32];
      sprintf(payload, "00,2,%lu,%lu", (unsigned long)raw_fuerza, (unsigned long)raw_ir);
      uint8_t xor_chk = Calcular_Checksum_XOR(payload);

      /* 4. Trama completa del protocolo industrial de MATLAB:
            Ejemplo: "@,00,2,145,218,2E;\r\n" */
      sprintf(tx_buffer, "@,%s,%02X;\r\n", payload, xor_chk);

      /* 5. Transmisión no bloqueante por USART2 a 115200 baudios */
      HAL_UART_Transmit(&huart2, (uint8_t*)tx_buffer, strlen(tx_buffer), 5);

      /* 6. Indicadores Visuales en los LEDs de la tarjeta Discovery */
      HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_15); // LED Azul: Pulso UART

      /* Si la fuerza supera el umbral crítico (> 2.8 N -> ~260 cuentas ADC), alerta */
      if (raw_fuerza > 260) {
        HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14, GPIO_PIN_SET);   // LED Rojo Alerta ON
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

/* =========================================================================
   CONFIGURACIONES OFICIALES DE PERIFÉRICOS HAL (STM32CubeMX)
   ========================================================================= */

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
  hadc1.Init.DMAContinuousRequests = DISABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  HAL_ADC_Init(&hadc1);
}

static void MX_TIM2_Init(void)
{
  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* Reloj APB1 = 84 MHz (Timer x2)
     Prescaler = 84 - 1 = 83 -> Reloj de conteo = 1 MHz (1 tick = 1 us)
     Periodo (ARR) = 4000 - 1 = 3999 -> T = 4000 us = 4.0 ms -> f = 250.0 Hz exactos */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 84 - 1;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 4000 - 1;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
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
  __HAL_RCC_GPIOD_CLK_ENABLE();

  /* Configuración de Pines Analógicos: PA1 (Fuerza) y PA4 (Infrarrojo) */
  GPIO_InitStruct.Pin = GPIO_PIN_1 | GPIO_PIN_4;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* Configuración de LEDs Discovery: PD12, PD13, PD14, PD15 */
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15, GPIO_PIN_RESET);
  GPIO_InitStruct.Pin = GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);
}

void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  HAL_RCC_OscConfig(&RCC_OscInitStruct);

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;
  HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5);
}
