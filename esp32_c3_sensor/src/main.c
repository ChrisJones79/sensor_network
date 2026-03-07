/*
 * esp32_c3_sensor/src/main.c
 *
 * ESP32-C3 BME680 BLE Sensor Node
 *
 * Reads temperature, humidity, pressure, and gas resistance from a BME680
 * via I2C, then broadcasts the latest readings as a BLE non-connectable
 * advertisement (beacon).  The nearest ESP32-CAM, acting as a BLE central,
 * scans for these packets and forwards them via MQTT to the backend.
 *
 * Node identity is derived from the BT MAC address so that each of the three
 * nodes is automatically distinguishable without any flashing-time config.
 *
 * ---- BLE advertisement layout ----
 *
 *  AD structure 1 — Flags (3 bytes)
 *    [0x02][0x01][0x06]   LE General Discoverable, BR/EDR Not Supported
 *
 *  AD structure 2 — Manufacturer Specific Data (28 bytes)
 *    [0x1B][0xFF]         length=27, type=Manufacturer Specific
 *    [0xFF][0xFF]         Company ID (0xFFFF = internal / test)
 *    [6 bytes]            Full BT MAC (big-endian, for node identification)
 *    [2 bytes]            Temperature  int16 LE  0.01 °C   (e.g. 2537=25.37)
 *    [2 bytes]            Humidity     uint16 LE 0.01 %RH  (e.g. 6412=64.12)
 *    [4 bytes]            Pressure     uint32 LE Pa        (e.g. 101325)
 *    [4 bytes]            Gas resist.  uint32 LE Ohm
 *    [1 byte]             Flags: bit0=TPH valid, bit1=gas valid, bit2=warming_up
 *    [4 bytes]            BME680 UID   uint32 LE  CRC32 of calibration bytes
 *
 * ---- Build-time config (set in platformio.ini build_flags) ----
 *
 *   BME680_I2C_ADDR      0x76 or 0x77 (SDO low = 0x76)
 *   BME680_SDA_PIN       GPIO number for I2C SDA
 *   BME680_SCL_PIN       GPIO number for I2C SCL
 *   SAMPLE_PERIOD_MS     Measurement interval in milliseconds
 *   HEATER_TEMP          Gas heater target temperature in °C (max 400)
 *   HEATER_DURATION_MS   Gas heater wait time in ms
 *   AMB_TEMP             Ambient temperature estimate for heater calc (°C)
 *   BLE_ADV_INT_MIN      BLE advertising interval minimum (units 0.625 ms)
 *   BLE_ADV_INT_MAX      BLE advertising interval maximum (units 0.625 ms)
 *   WARM_UP_DURATION_S   Seconds to assert warming_up after each power-on (default 1800 = 30 min)
 */

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "driver/i2c.h"
#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

/* -------------------------------------------------------------------------
 * Compile-time defaults (overridden by platformio.ini build_flags)
 * ---------------------------------------------------------------------- */

#ifndef BME680_I2C_ADDR
#define BME680_I2C_ADDR        0x77
#endif

#ifndef BME680_SDA_PIN
#define BME680_SDA_PIN         6
#endif

#ifndef BME680_SCL_PIN
#define BME680_SCL_PIN         7
#endif

#ifndef SAMPLE_PERIOD_MS
#define SAMPLE_PERIOD_MS       10000U
#endif

#ifndef HEATER_TEMP
#define HEATER_TEMP            300U
#endif

#ifndef HEATER_DURATION_MS
#define HEATER_DURATION_MS     150U
#endif

#ifndef AMB_TEMP
#define AMB_TEMP               25
#endif

#ifndef BLE_ADV_INT_MIN
#define BLE_ADV_INT_MIN        0x40
#endif

#ifndef BLE_ADV_INT_MAX
#define BLE_ADV_INT_MAX        0x80
#endif

#ifndef WARM_UP_DURATION_S
#define WARM_UP_DURATION_S     1800U   /* 30 minutes */
#endif

/* -------------------------------------------------------------------------
 * BME680 register addresses
 * ---------------------------------------------------------------------- */

#define BME680_REG_RES_HEAT_VAL   0x00U  /* int8, trimming value */
#define BME680_REG_RES_HEAT_RANGE 0x02U  /* bits [5:4] */
#define BME680_REG_RANGE_SW_ERR   0x04U  /* bits [7:4] */
#define BME680_REG_FIELD0         0x1DU  /* meas_status_0 + raw data */
#define BME680_REG_RES_HEAT_0     0x5AU  /* heater target resistance */
#define BME680_REG_GAS_WAIT_0     0x64U  /* heater wait duration */
#define BME680_REG_CTRL_GAS_1     0x71U  /* run_gas[4], nb_conv[3:0] */
#define BME680_REG_CTRL_HUM       0x72U  /* osrs_h[2:0] */
#define BME680_REG_CTRL_MEAS      0x74U  /* osrs_t[7:5], osrs_p[4:2], mode[1:0] */
#define BME680_REG_CONFIG         0x75U  /* filter[4:2] */
#define BME680_REG_COEFF1         0x8AU  /* 23 calibration bytes */
#define BME680_REG_CHIP_ID        0xD0U
#define BME680_REG_RESET          0xE0U
#define BME680_REG_COEFF2         0xE1U  /* 14 calibration bytes */

#define BME680_CHIP_ID_VAL        0x61U  /* BME680; BME688 = 0x61 too */
#define BME680_SOFT_RESET_VAL     0xB6U

/* meas_status_0 (0x1D) bits */
#define BME680_NEW_DATA_MSK       0x80U
#define BME680_MEASURING_MSK      0x10U

/* gas LSB register (0x2B) bits */
#define BME680_GAS_VALID_MSK      0x20U
#define BME680_HEAT_STAB_MSK      0x10U

/* Oversampling codes */
#define BME680_OSS_SKIP           0x00U
#define BME680_OSS_1X             0x01U
#define BME680_OSS_2X             0x02U
#define BME680_OSS_4X             0x03U
#define BME680_OSS_8X             0x04U
#define BME680_OSS_16X            0x05U

/* IIR filter coefficient */
#define BME680_FILTER_3           0x02U

/* Forced mode */
#define BME680_MODE_FORCED        0x01U
#define BME680_MODE_SLEEP         0x00U

/* -------------------------------------------------------------------------
 * BME680 calibration data
 * ---------------------------------------------------------------------- */

typedef struct {
    /* Temperature */
    uint16_t par_t1;
    int16_t  par_t2;
    int8_t   par_t3;
    /* Pressure */
    uint16_t par_p1;
    int16_t  par_p2;
    int8_t   par_p3;
    int16_t  par_p4;
    int16_t  par_p5;
    int8_t   par_p6;
    int8_t   par_p7;
    int16_t  par_p8;
    int16_t  par_p9;
    uint8_t  par_p10;
    /* Humidity */
    uint16_t par_h1;
    uint16_t par_h2;
    int8_t   par_h3;
    int8_t   par_h4;
    int8_t   par_h5;
    uint8_t  par_h6;
    int8_t   par_h7;
    /* Gas heater */
    int8_t   par_gh1;
    int16_t  par_gh2;
    int8_t   par_gh3;
    uint8_t  res_heat_range;
    int8_t   res_heat_val;
    int8_t   range_sw_err;
    /* Running fine temperature used by pressure/humidity compensation */
    int32_t  t_fine;
} bme680_calib_t;

/* -------------------------------------------------------------------------
 * Measurement result
 * ---------------------------------------------------------------------- */

typedef struct {
    bool     valid;           /* TPH measurement valid */
    bool     gas_valid;       /* gas measurement valid and heater stable */
    int16_t  temperature;     /* 0.01 °C   (e.g. 2537 = 25.37 °C) */
    uint16_t humidity;        /* 0.01 %RH  (e.g. 6412 = 64.12 %RH) */
    uint32_t pressure;        /* Pa        (e.g. 101325) */
    uint32_t gas_resistance;  /* Ohm */
} bme680_data_t;

/* -------------------------------------------------------------------------
 * Globals
 * ---------------------------------------------------------------------- */

static const char *TAG = "c3_sensor";
static bme680_calib_t s_calib;
static uint8_t        s_bt_mac[6];

/* BME680 hardware UID: CRC32 of raw calibration bytes, computed once on init */
static uint32_t s_bme680_uid = 0;

/* BLE advertisement raw buffer (max 31 bytes) */
static uint8_t  s_adv_buf[31];
static uint8_t  s_adv_len = 0;
static volatile bool s_ble_advertising = false;

/* -------------------------------------------------------------------------
 * I2C helpers
 * ---------------------------------------------------------------------- */

static void init_i2c(void)
{
    i2c_config_t cfg = {
        .mode             = I2C_MODE_MASTER,
        .sda_io_num       = BME680_SDA_PIN,
        .scl_io_num       = BME680_SCL_PIN,
        .sda_pullup_en    = GPIO_PULLUP_ENABLE,
        .scl_pullup_en    = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_NUM_0, &cfg));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_NUM_0, I2C_MODE_MASTER, 0, 0, 0));
}

static esp_err_t i2c_read(uint8_t reg, uint8_t *data, size_t len)
{
    return i2c_master_write_read_device(
        I2C_NUM_0, BME680_I2C_ADDR,
        &reg, 1,
        data, len,
        pdMS_TO_TICKS(50));
}

static esp_err_t i2c_write_byte(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_write_to_device(
        I2C_NUM_0, BME680_I2C_ADDR,
        buf, sizeof(buf),
        pdMS_TO_TICKS(50));
}

/* -------------------------------------------------------------------------
 * CRC32 (ISO 3309 / Ethernet polynomial 0xEDB88320, reflected)
 * Used to derive a unique hardware ID from the BME680 calibration bytes.
 * ---------------------------------------------------------------------- */

static uint32_t crc32_compute(const uint8_t *data, size_t len)
{
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320U & (uint32_t)(-(int32_t)(crc & 1U)));
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

/* -------------------------------------------------------------------------
 * BME680 calibration read
 *
 * Bosch BME680/BME68x calibration register map:
 *   Coeff1: 23 bytes from 0x8A
 *   Coeff2: 14 bytes from 0xE1
 *   Coeff3:  5 bytes from 0x00  (res_heat_val / res_heat_range / range_sw_err)
 * ---------------------------------------------------------------------- */

static bool bme680_read_calibration(void)
{
    uint8_t c1[23] = {0};
    uint8_t c2[14] = {0};
    uint8_t c3[5]  = {0};

    if (i2c_read(BME680_REG_COEFF1, c1, sizeof(c1)) != ESP_OK) return false;
    if (i2c_read(BME680_REG_COEFF2, c2, sizeof(c2)) != ESP_OK) return false;
    if (i2c_read(0x00U,             c3, sizeof(c3)) != ESP_OK) return false;

    /* Compute hardware UID from raw calibration bytes.
     * The BME680 has no factory-programmed UID register; however, the
     * calibration coefficients are unique per chip due to manufacturing
     * variation, making CRC32(c1 || c2) a reliable chip fingerprint. */
    uint8_t calib_raw[37];
    memcpy(calib_raw,        c1, sizeof(c1));
    memcpy(calib_raw + 23,   c2, sizeof(c2));
    s_bme680_uid = crc32_compute(calib_raw, sizeof(calib_raw));
    ESP_LOGI("bme680_calib", "BME680 UID: %08" PRIx32, s_bme680_uid);

    /* Temperature (coeff1 offsets) */
    s_calib.par_t2  = (int16_t) ((uint16_t)c1[1] << 8 | c1[0]);
    s_calib.par_t3  = (int8_t)  c1[2];
    /* Pressure */
    s_calib.par_p1  = (uint16_t)((uint16_t)c1[5]  << 8 | c1[4]);
    s_calib.par_p2  = (int16_t) ((uint16_t)c1[7]  << 8 | c1[6]);
    s_calib.par_p3  = (int8_t)  c1[8];
    s_calib.par_p4  = (int16_t) ((uint16_t)c1[11] << 8 | c1[10]);
    s_calib.par_p5  = (int16_t) ((uint16_t)c1[13] << 8 | c1[12]);
    s_calib.par_p7  = (int8_t)  c1[14];
    s_calib.par_p6  = (int8_t)  c1[15];
    s_calib.par_p8  = (int16_t) ((uint16_t)c1[19] << 8 | c1[18]);
    s_calib.par_p9  = (int16_t) ((uint16_t)c1[21] << 8 | c1[20]);
    s_calib.par_p10 = c1[22];

    /* Humidity (coeff2 offsets from 0xE1) */
    s_calib.par_h2  = (uint16_t)(((uint16_t)c2[0] << 4) | ((uint16_t)c2[1] >> 4));
    s_calib.par_h1  = (uint16_t)(((uint16_t)c2[2] << 4) | ((uint16_t)c2[1] & 0x0FU));
    s_calib.par_h3  = (int8_t)  c2[3];
    s_calib.par_h4  = (int8_t)  c2[4];
    s_calib.par_h5  = (int8_t)  c2[5];
    s_calib.par_h6  = c2[6];
    s_calib.par_h7  = (int8_t)  c2[7];

    /* T1 and gas heater coefficients (coeff2 offsets 8..13) */
    s_calib.par_t1  = (uint16_t)((uint16_t)c2[9]  << 8 | c2[8]);
    s_calib.par_gh2 = (int16_t) ((uint16_t)c2[11] << 8 | c2[10]);
    s_calib.par_gh1 = (int8_t)  c2[12];
    s_calib.par_gh3 = (int8_t)  c2[13];

    /* Heater trim (coeff3 from 0x00) */
    s_calib.res_heat_val   = (int8_t) c3[0];
    s_calib.res_heat_range = (c3[2] & 0x30U) >> 4;
    s_calib.range_sw_err   = (int8_t)((int8_t)c3[4] >> 4);

    return true;
}

/* -------------------------------------------------------------------------
 * BME680 compensation formulas
 * (Integer-only, derived from Bosch BST-BME680-DS001 Appendix B)
 * ---------------------------------------------------------------------- */

/* Returns temperature in 0.01 °C; also updates calib->t_fine. */
static int16_t bme680_comp_temp(bme680_calib_t *calib, uint32_t adc_temp)
{
    int64_t var1 = ((int32_t)adc_temp >> 3) - ((int32_t)calib->par_t1 << 1);
    int64_t var2 = (var1 * (int32_t)calib->par_t2) >> 11;
    int64_t var3 = ((var1 >> 1) * (var1 >> 1)) >> 12;
    var3 = (var3 * ((int32_t)calib->par_t3 << 4)) >> 14;
    calib->t_fine = (int32_t)(var2 + var3);
    return (int16_t)(((calib->t_fine * 5) + 128) >> 8);
}

/* Returns pressure in Pa. Must call bme680_comp_temp first. */
static uint32_t bme680_comp_pressure(const bme680_calib_t *calib, uint32_t adc_pres)
{
    int32_t var1 = ((int32_t)calib->t_fine >> 1) - 64000;
    int32_t var2 = ((((var1 >> 2) * (var1 >> 2)) >> 11) * (int32_t)calib->par_p6) >> 2;
    var2 = var2 + ((var1 * (int32_t)calib->par_p5) << 1);
    var2 = (var2 >> 2) + ((int32_t)calib->par_p4 << 16);
    var1 = (((((var1 >> 2) * (var1 >> 2)) >> 13) * ((int32_t)calib->par_p3 << 5)) >> 3) +
           (((int32_t)calib->par_p2 * var1) >> 1);
    var1 = var1 >> 18;
    var1 = ((32768 + var1) * (int32_t)calib->par_p1) >> 15;

    int32_t comp_pres = 1048576 - (int32_t)adc_pres;
    comp_pres = (int32_t)((comp_pres - (var2 >> 12)) * (uint32_t)3125);
    if (comp_pres >= (int32_t)0x40000000) {
        comp_pres = (comp_pres / var1) << 1;
    } else {
        comp_pres = (comp_pres << 1) / var1;
    }

    var1 = ((int32_t)calib->par_p9 *
            (int32_t)(((comp_pres >> 3) * (comp_pres >> 3)) >> 13)) >> 12;
    var2 = ((int32_t)(comp_pres >> 2) * (int32_t)calib->par_p8) >> 13;
    int32_t var3 =
        ((int32_t)(comp_pres >> 8) * (int32_t)(comp_pres >> 8) *
         (int32_t)(comp_pres >> 8) * (int32_t)calib->par_p10) >> 17;

    comp_pres = comp_pres +
                ((var1 + var2 + var3 + ((int32_t)calib->par_p7 << 7)) >> 4);
    return (uint32_t)comp_pres;
}

/* Returns humidity in 0.001 %RH. Must call bme680_comp_temp first. */
static uint32_t bme680_comp_humidity(const bme680_calib_t *calib, uint16_t adc_hum)
{
    int32_t var1 = (int32_t)adc_hum -
                   (int32_t)((int32_t)calib->par_h1 << 4) -
                   ((calib->t_fine * (int32_t)calib->par_h3 / 100) >> 1);

    int32_t var2 =
        (int32_t)calib->par_h2 *
        (((calib->t_fine * (int32_t)calib->par_h4 / 100) +
          (((calib->t_fine * ((calib->t_fine * (int32_t)calib->par_h5 / 100)) >> 6) / 100) >> 6) +
          (1 << 14)) >> 10);

    int32_t var3 = var1 * var2;
    int32_t var4 = (int32_t)calib->par_h6;
    var4 = ((var4 * ((var3 >> 14) * (var3 >> 14))) >> 10);
    int32_t var5 = var3 - (var4 << 6);
    int32_t comp_hum = (var5 + ((int32_t)calib->par_h7 * calib->t_fine >> 8)) >> 12;

    if (comp_hum > 100000) comp_hum = 100000;
    if (comp_hum < 0)      comp_hum = 0;
    return (uint32_t)comp_hum;
}

/* Returns gas resistance in Ohm. */
static uint32_t bme680_comp_gas_resistance(const bme680_calib_t *calib,
                                           uint16_t adc_gas, uint8_t gas_range)
{
    /* Bosch lookup tables for the low-range gas resistance formula */
    static const uint32_t lut1[16] = {
        2147483647UL, 2147483647UL, 2147483647UL, 2147483647UL,
        2147483647UL, 2126008810UL, 2147483647UL, 2130303777UL,
        2147483647UL, 2147483647UL, 2143188679UL, 2136746228UL,
        2147483647UL, 2126008810UL, 2147483647UL, 2147483647UL,
    };
    static const uint32_t lut2[16] = {
        4096000000UL, 2048000000UL, 1024000000UL, 512000000UL,
        255744255UL,  127110228UL,  64000000UL,   32258064UL,
        16016016UL,   8000000UL,    4000000UL,    2000000UL,
        1000000UL,    500000UL,     250000UL,      125000UL,
    };

    int64_t var1 = (int64_t)((1340 + (5 * (int64_t)calib->range_sw_err)) *
                             (int64_t)lut1[gas_range]) >> 16;
    uint64_t var2 = (uint64_t)(((int64_t)(adc_gas << 15) - 16777216LL) + var1);
    int64_t var3 = (int64_t)((uint64_t)lut2[gas_range] * (uint64_t)var1) >> 9;
    return (uint32_t)((var3 + ((int64_t)var2 >> 1)) / (int64_t)var2);
}

/* -------------------------------------------------------------------------
 * BME680 heater configuration helpers
 * ---------------------------------------------------------------------- */

/* Encodes heater wait time to BME680 gas_wait register format. */
static uint8_t bme680_encode_gas_wait(uint16_t dur_ms)
{
    uint8_t factor = 0;
    uint8_t durval;

    if (dur_ms >= 0xFC0U) {
        durval = 0xFFU;
    } else {
        while (dur_ms > 0x3FU) {
            dur_ms /= 4U;
            factor += 1U;
        }
        durval = (uint8_t)(dur_ms + (uint8_t)(factor * 64U));
    }
    return durval;
}

/* Calculates res_heat_0 register value for a target heater temperature. */
static uint8_t bme680_calc_res_heat(uint16_t tgt_temp_c, int32_t amb_temp_c)
{
    if (tgt_temp_c > 400U) tgt_temp_c = 400U;

    int32_t var1 = ((int32_t)amb_temp_c * (int32_t)s_calib.par_gh3) / 1000 * 256;
    int32_t var2 = (s_calib.par_gh1 + 784) *
                   ((((s_calib.par_gh2 + 154009) * (int32_t)tgt_temp_c * 5) / 100 +
                     3276800) / 10);
    int32_t var3 = var1 + (var2 / 2);
    int32_t var4 = var3 / ((int32_t)s_calib.res_heat_range + 4);
    int32_t var5 = (131 * (int32_t)s_calib.res_heat_val) + 65536;
    int32_t res_x100 = (int32_t)(((var4 / var5) - 250) * 34);
    return (uint8_t)((res_x100 + 50) / 100);
}

/* -------------------------------------------------------------------------
 * BME680 init and forced-mode measurement
 * ---------------------------------------------------------------------- */

static bool bme680_init(void)
{
    /* Soft reset */
    if (i2c_write_byte(BME680_REG_RESET, BME680_SOFT_RESET_VAL) != ESP_OK) {
        ESP_LOGE(TAG, "BME680: soft reset write failed");
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(5));

    /* Check chip ID */
    uint8_t chip_id = 0;
    if (i2c_read(BME680_REG_CHIP_ID, &chip_id, 1) != ESP_OK || chip_id != BME680_CHIP_ID_VAL) {
        ESP_LOGE(TAG, "BME680: chip ID mismatch: got 0x%02X, want 0x%02X",
                 chip_id, BME680_CHIP_ID_VAL);
        return false;
    }
    ESP_LOGI(TAG, "BME680: chip ID 0x%02X OK", chip_id);

    if (!bme680_read_calibration()) {
        ESP_LOGE(TAG, "BME680: calibration read failed");
        return false;
    }
    ESP_LOGI(TAG, "BME680: calibration loaded (T1=%u T2=%d P1=%u H1=%u)",
             s_calib.par_t1, s_calib.par_t2, s_calib.par_p1, s_calib.par_h1);
    return true;
}

/*
 * Performs one forced-mode measurement and populates *out.
 * Blocks for the duration of the measurement (heater + TPH settle).
 * Returns true on success, false if the sensor did not respond or
 * reported no new data within the timeout.
 */
static bool bme680_measure(bme680_data_t *out)
{
    memset(out, 0, sizeof(*out));

    /* 1. Humidity oversampling */
    if (i2c_write_byte(BME680_REG_CTRL_HUM, BME680_OSS_4X) != ESP_OK) return false;

    /* 2. IIR filter coefficient */
    if (i2c_write_byte(BME680_REG_CONFIG, (uint8_t)(BME680_FILTER_3 << 2)) != ESP_OK) return false;

    /* 3. Gas heater: target resistance and wait time */
    uint8_t res_heat = bme680_calc_res_heat(HEATER_TEMP, AMB_TEMP);
    uint8_t gas_wait = bme680_encode_gas_wait(HEATER_DURATION_MS);
    if (i2c_write_byte(BME680_REG_RES_HEAT_0, res_heat) != ESP_OK) return false;
    if (i2c_write_byte(BME680_REG_GAS_WAIT_0, gas_wait) != ESP_OK) return false;

    /* 4. Enable gas measurement (run_gas=1, nb_conv=0 selects heater profile 0) */
    if (i2c_write_byte(BME680_REG_CTRL_GAS_1, 0x10U) != ESP_OK) return false;

    /* 5. Start forced mode: osrs_t=4x, osrs_p=4x, mode=01 */
    uint8_t ctrl_meas = (uint8_t)((BME680_OSS_4X << 5) |
                                   (BME680_OSS_4X << 2) |
                                   BME680_MODE_FORCED);
    if (i2c_write_byte(BME680_REG_CTRL_MEAS, ctrl_meas) != ESP_OK) return false;

    /* 6. Poll new_data_0 (bit7 of 0x1D) — timeout ~500 ms */
    bool new_data = false;
    for (int i = 0; i < 50; i++) {
        vTaskDelay(pdMS_TO_TICKS(10));
        uint8_t status = 0;
        if (i2c_read(BME680_REG_FIELD0, &status, 1) == ESP_OK &&
            (status & BME680_NEW_DATA_MSK)) {
            new_data = true;
            break;
        }
    }
    if (!new_data) {
        ESP_LOGW(TAG, "BME680: timeout waiting for new data");
        return false;
    }

    /* 7. Burst-read field0 registers: 0x1D..0x2B (15 bytes) */
    uint8_t buf[15] = {0};
    if (i2c_read(BME680_REG_FIELD0, buf, sizeof(buf)) != ESP_OK) return false;

    /* buf[0] = 0x1D meas_status_0  (already checked new_data bit) */
    uint32_t adc_pres = ((uint32_t)buf[2] << 12) | ((uint32_t)buf[3] << 4) | (buf[4] >> 4);
    uint32_t adc_temp = ((uint32_t)buf[5] << 12) | ((uint32_t)buf[6] << 4) | (buf[7] >> 4);
    uint16_t adc_hum  = ((uint16_t)buf[8] << 8)  | buf[9];
    uint16_t adc_gas  = ((uint16_t)buf[13] << 2)  | (buf[14] >> 6);
    uint8_t  gas_range = buf[14] & 0x0FU;
    bool     gas_valid = (buf[14] & BME680_GAS_VALID_MSK) != 0 &&
                         (buf[14] & BME680_HEAT_STAB_MSK) != 0;

    /* 8. Apply compensation formulas */
    int16_t  temp     = bme680_comp_temp(&s_calib, adc_temp);   /* updates t_fine */
    uint32_t pres     = bme680_comp_pressure(&s_calib, adc_pres);
    uint32_t hum_mpct = bme680_comp_humidity(&s_calib, adc_hum); /* 0.001 %RH */

    /* Convert humidity from 0.001 %RH → 0.01 %RH (fits in uint16) */
    uint16_t hum = (uint16_t)(hum_mpct / 10U);

    out->valid        = true;
    out->gas_valid    = gas_valid;
    out->temperature  = temp;
    out->humidity     = hum;
    out->pressure     = pres;
    out->gas_resistance = gas_valid ?
        bme680_comp_gas_resistance(&s_calib, adc_gas, gas_range) : 0U;

    ESP_LOGI(TAG, "BME680: T=%.2f°C  H=%.2f%%  P=%lu Pa  G=%lu Ω%s",
             (double)temp / 100.0,
             (double)hum  / 100.0,
             (unsigned long)pres,
             (unsigned long)out->gas_resistance,
             gas_valid ? "" : " (gas N/A)");
    return true;
}

/* -------------------------------------------------------------------------
 * BLE advertisement builder
 *
 * Manufacturer-specific AD payload (27 bytes):
 *   [0-1]   Company ID  0xFF 0xFF
 *   [2-7]   BT MAC      big-endian
 *   [8-9]   Temperature int16 LE  0.01 °C
 *   [10-11] Humidity    uint16 LE 0.01 %RH
 *   [12-15] Pressure    uint32 LE Pa
 *   [16-19] Gas resist  uint32 LE Ohm
 *   [20]    Flags       bit0=TPH valid, bit1=gas valid, bit2=warming_up
 *   [21-24] BME680 UID  uint32 LE  CRC32 of calibration bytes
 *
 * Total raw ADV_DATA: 3 (Flags AD) + 28 (Mfr AD) = 31 bytes (BLE maximum).
 * ---------------------------------------------------------------------- */

static bool adv_is_warming_up(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000000ULL) < (uint64_t)WARM_UP_DURATION_S;
}

static void build_adv_payload(const bme680_data_t *d)
{
    const bool warming_up = adv_is_warming_up();

    uint8_t mfr[27] = {0};
    /* Company ID */
    mfr[0] = 0xFFU;
    mfr[1] = 0xFFU;
    /* BT MAC (big-endian so it reads naturally in a sniffer) */
    memcpy(&mfr[2], s_bt_mac, 6);
    /* Temperature */
    mfr[8]  = (uint8_t)((uint16_t)d->temperature & 0xFFU);
    mfr[9]  = (uint8_t)((uint16_t)d->temperature >> 8);
    /* Humidity */
    mfr[10] = (uint8_t)(d->humidity & 0xFFU);
    mfr[11] = (uint8_t)(d->humidity >> 8);
    /* Pressure */
    mfr[12] = (uint8_t)(d->pressure & 0xFFU);
    mfr[13] = (uint8_t)((d->pressure >> 8)  & 0xFFU);
    mfr[14] = (uint8_t)((d->pressure >> 16) & 0xFFU);
    mfr[15] = (uint8_t)((d->pressure >> 24) & 0xFFU);
    /* Gas resistance */
    mfr[16] = (uint8_t)(d->gas_resistance & 0xFFU);
    mfr[17] = (uint8_t)((d->gas_resistance >> 8)  & 0xFFU);
    mfr[18] = (uint8_t)((d->gas_resistance >> 16) & 0xFFU);
    mfr[19] = (uint8_t)((d->gas_resistance >> 24) & 0xFFU);
    /* Flags */
    mfr[20] = (d->valid     ? 0x01U : 0x00U)
            | (d->gas_valid ? 0x02U : 0x00U)
            | (warming_up   ? 0x04U : 0x00U);
    /* BME680 hardware UID (CRC32 of calibration bytes, LE) */
    mfr[21] = (uint8_t)(s_bme680_uid & 0xFFU);
    mfr[22] = (uint8_t)((s_bme680_uid >> 8)  & 0xFFU);
    mfr[23] = (uint8_t)((s_bme680_uid >> 16) & 0xFFU);
    mfr[24] = (uint8_t)((s_bme680_uid >> 24) & 0xFFU);

    /* Build raw ADV_DATA:
     *   [0x02][0x01][0x06]         — Flags AD (3 bytes)
     *   [0x1C][0xFF][mfr 27 bytes] — Manufacturer Specific AD (29 bytes)
     *   Total: 32? No: length byte counts type+data = 1+27 = 28, so byte = 0x1C */
    uint8_t *p = s_adv_buf;
    *p++ = 0x02U; *p++ = 0x01U; *p++ = 0x06U;
    *p++ = (uint8_t)(1U + sizeof(mfr));  /* length field = type(1) + data(27) = 28 = 0x1C */
    *p++ = 0xFFU;                        /* type: Manufacturer Specific */
    memcpy(p, mfr, sizeof(mfr));
    p += sizeof(mfr);
    s_adv_len = (uint8_t)(p - s_adv_buf);
}

/* -------------------------------------------------------------------------
 * BLE GAP callback
 * ---------------------------------------------------------------------- */

static esp_ble_adv_params_t s_adv_params = {
    .adv_int_min       = BLE_ADV_INT_MIN,
    .adv_int_max       = BLE_ADV_INT_MAX,
    .adv_type          = ADV_TYPE_NONCONN_IND,
    .own_addr_type     = BLE_ADDR_TYPE_PUBLIC,
    .channel_map       = ADV_CHNL_ALL,
    .adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
};

static void gap_event_handler(esp_gap_ble_cb_event_t event,
                               esp_ble_gap_cb_param_t *param)
{
    switch (event) {
        case ESP_GAP_BLE_ADV_DATA_RAW_SET_COMPLETE_EVT:
            esp_ble_gap_start_advertising(&s_adv_params);
            break;

        case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
            if (param->adv_start_cmpl.status != ESP_BT_STATUS_SUCCESS) {
                ESP_LOGE(TAG, "BLE adv start failed: %d",
                         param->adv_start_cmpl.status);
            } else {
                s_ble_advertising = true;
            }
            break;

        case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
            s_ble_advertising = false;
            /* Reconfigure with the latest data, then restart */
            esp_ble_gap_config_adv_data_raw(s_adv_buf, s_adv_len);
            break;

        default:
            break;
    }
}

/* -------------------------------------------------------------------------
 * BLE init
 * ---------------------------------------------------------------------- */

static void init_ble(void)
{
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_BLE));
    ESP_ERROR_CHECK(esp_bluedroid_init());
    ESP_ERROR_CHECK(esp_bluedroid_enable());
    ESP_ERROR_CHECK(esp_ble_gap_register_callback(gap_event_handler));

    /* Read the BT MAC for node identification */
    ESP_ERROR_CHECK(esp_read_mac(s_bt_mac, ESP_MAC_BT));
    ESP_LOGI(TAG, "BT MAC: %02X:%02X:%02X:%02X:%02X:%02X",
             s_bt_mac[0], s_bt_mac[1], s_bt_mac[2],
             s_bt_mac[3], s_bt_mac[4], s_bt_mac[5]);

    /* Set a human-readable device name (useful for passive scanning debug) */
    char name[24];
    snprintf(name, sizeof(name), "bme680_%02X%02X%02X",
             s_bt_mac[3], s_bt_mac[4], s_bt_mac[5]);
    ESP_ERROR_CHECK(esp_ble_gap_set_device_name(name));
}

/* -------------------------------------------------------------------------
 * Sensor task
 *
 * Takes a BME680 measurement every SAMPLE_PERIOD_MS milliseconds, builds
 * the BLE advertisement payload, and triggers an advertising restart so
 * the nearest ESP32-CAM scanner picks up the latest data.
 * ---------------------------------------------------------------------- */

static void sensor_task(void *arg)
{
    (void)arg;

    /* Take the first measurement before starting to advertise */
    bme680_data_t data = {0};
    if (!bme680_measure(&data)) {
        ESP_LOGW(TAG, "Initial BME680 read failed; advertising with zero data");
    }

    build_adv_payload(&data);

    /* Kick off BLE advertising for the first time */
    esp_ble_gap_config_adv_data_raw(s_adv_buf, s_adv_len);

    TickType_t last_wake = xTaskGetTickCount();

    while (true) {
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));

        bme680_data_t new_data = {0};
        if (bme680_measure(&new_data)) {
            build_adv_payload(&new_data);
        }

        /*
         * Update the advertisement.  If currently advertising, stop it —
         * the GAP callback will re-configure and restart automatically.
         * If not currently advertising (e.g. still starting), just push
         * the new raw data directly.
         */
        if (s_ble_advertising) {
            esp_ble_gap_stop_advertising();
        } else {
            esp_ble_gap_config_adv_data_raw(s_adv_buf, s_adv_len);
        }
    }
}

/* -------------------------------------------------------------------------
 * Entry point
 * ---------------------------------------------------------------------- */

void app_main(void)
{
    /* NVS flash required by BT stack */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    init_i2c();
    ESP_LOGI(TAG, "I2C initialised (SDA=%d SCL=%d addr=0x%02X)",
             BME680_SDA_PIN, BME680_SCL_PIN, BME680_I2C_ADDR);

    if (!bme680_init()) {
        ESP_LOGE(TAG, "BME680 init failed — check wiring and I2C address");
        /* Continue so the BLE beacon still advertises (with invalid flag set) */
    }

    init_ble();

    /* Stack size: compensates for BME680 stack-allocated buffers and BLE calls */
    xTaskCreate(sensor_task, "sensor_task", 4096, NULL, 5, NULL);
}
