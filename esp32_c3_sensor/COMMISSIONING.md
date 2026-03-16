# ESP32-C3 BME680 Sensor Node Commissioning

## Overview

Each ESP32-C3 node reads temperature, humidity, pressure, and gas resistance
from a BME680 over I2C, then broadcasts the values as a BLE non-connectable
advertisement (beacon) every `SAMPLE_PERIOD_MS` milliseconds.

The nearest ESP32-CAM, acting as a BLE central scanner, picks up these packets
and forwards them via MQTT to the backend. Three nodes can run simultaneously
— they are distinguished by the BT MAC address embedded in every advertisement.

---

## 1) Hardware wiring

### BME680 → ESP32-C3 DevKitM-1 # TODO: it's not a devkit. ESP32-C3 HW-466AB SuperMini

| BME680 pin | ESP32-C3 pin     | Notes                             |
| ---------- | ---------------- | --------------------------------- |
| VCC        | 3.3 V            | Do **not** use 5 V                |
| GND        | GND              |                                   |
| SDA        | GPIO 6           | Configurable via `BME680_SDA_PIN` |
| SCL        | GPIO 7           | Configurable via `BME680_SCL_PIN` |
| SDO        | GND **or** 3.3 V | GND → I2C addr 0x76; 3.3 V → 0x77 |
| CS         | 3.3 V            | Selects I2C mode                  |

If you pull SDO low (0x76), also set `BME680_I2C_ADDR=0x76` in `platformio.ini`.

---

## 2) Build configuration

Edit `platformio.ini` `build_flags` before flashing:

| Flag                 | Default      | Description                                    |
| -------------------- | ------------ | ---------------------------------------------- |
| `BME680_I2C_ADDR`    | `0x77`       | I2C address (0x76 or 0x77)                     |
| `BME680_SDA_PIN`     | `6`          | GPIO for SDA                                   |
| `BME680_SCL_PIN`     | `7`          | GPIO for SCL                                   |
| `SAMPLE_PERIOD_MS`   | `10000`      | Measurement interval in ms                     |
| `HEATER_TEMP`        | `300`        | Gas heater target °C (max 400)                 |
| `HEATER_DURATION_MS` | `150`        | Gas heater stabilisation time in ms            |
| `AMB_TEMP`           | `25`         | Ambient °C estimate for heater resistance calc | # TODO: it's colder here, lower ambient
| `BLE_ADV_INT_MIN`    | `0x40`       | Min advertising interval (units of 0.625 ms)   |
| `BLE_ADV_INT_MAX`    | `0x80`       | Max advertising interval (units of 0.625 ms)   |
| `WARM_UP_DURATION_S` | `1800`       | Seconds to assert warming_up after each boot   |
| `NODE_GROUP`         | `"all"`      | Group tag (informational, not yet used)        |
| `SENSOR_SID`         | `"bme680_0"` | Sensor ID tag (informational)                  |

All three nodes use the same firmware binary — their node IDs are derived
automatically from the BT MAC address, so no per-node configuration is needed.

---

## 3) Flash and verify

```bash
cd esp32_c3_sensor
pio run --target upload --target monitor
```

On boot the serial log prints:

```text
I (xxx) c3_sensor: I2C initialised (SDA=6 SCL=7 addr=0x77)
I (xxx) c3_sensor: BME680: chip ID 0x61 OK
I (xxx) c3_sensor: BME680: UID a1b2c3d4
I (xxx) c3_sensor: BME680: calibration loaded (T1=… T2=… P1=… H1=…)
I (xxx) c3_sensor: BT MAC: AA:BB:CC:DD:EE:FF
I (xxx) c3_sensor: BME680: T=25.37°C  H=64.12%  P=101325 Pa  G=85432 Ω
```

If you see `chip ID mismatch` or I2C errors, double-check wiring and the SDO
pin / address setting.

---

## 4) BLE advertisement format

Use any BLE scanner (e.g. nRF Connect) to verify the node is advertising.
Look for a device named `bme680_XXYYZZ` (last 3 MAC octets in hex).

Manufacturer-specific data payload (after the 2-byte company ID `0xFF 0xFF`):

| Offset | Length | Field          | Units                                     |
| ------ | ------ | -------------- | ----------------------------------------- |
| 2      | 6      | BT MAC         | big-endian                                |
| 8      | 2      | Temperature    | int16 LE, 0.01 °C                         |
| 10     | 2      | Humidity       | uint16 LE, 0.01 %RH                       |
| 12     | 4      | Pressure       | uint32 LE, Pa                             |
| 16     | 4      | Gas resistance | uint32 LE, Ω                              |
| 20     | 1      | Flags          | bit0=TPH ok, bit1=gas ok, bit2=warming_up |
| 21     | 4      | BME680 UID     | uint32 LE, factory registers 0x83–0x86    |

The BME680 UID is a factory-programmed value read from undocumented registers
`0x83–0x86` using the formula confirmed by Bosch:

```c
uid = (((uid_regs[3] + (uid_regs[2] << 8)) & 0x7FFF) << 16)
      + (uid_regs[1] << 8) + uid_regs[0];
```

This UID is used by the backend to track each physical chip's burn-in and
warm-up history independently of which node it is attached to.

---

## 5) BME680 burn-in and warm-up tracking

The backend maintains a catalog of every BME680 chip seen in the network.
Once the ESP32-CAM BLE central is implemented it will call
`POST /api/bme680/register` on each received advertisement, driving the
following state machine:

| State                     | Meaning                                  |
| ------------------------- | ---------------------------------------- |
| `in_progress=true`        | Burn-in accumulating hours towards 48 h  |
| `burn_in_successful=true` | 48-hour burn-in completed                |
| `retry_needed=true`       | Previous attempt interrupted before 48 h |
| `warm_up_active=true`     | 30-min post-power-on warm-up in progress |

The `warming_up` flag (bit2 of the Flags byte) is asserted by firmware for
`WARM_UP_DURATION_S` seconds after each boot. The backend uses it to:

- Detect reboots that interrupted an active burn-in → marks `retry_needed`.
- Open a warm-up event (once burn-in is successful) and close it when the
  flag clears.

---

## 6) ESP32-CAM BLE central (next step)

The ESP32-CAM firmware needs to be extended to:

1. Run the BLE stack in central/scanner mode alongside Wi-Fi (coexistence).
2. Scan for manufacturer-specific advertisements with company ID `0xFF 0xFF`.
3. Parse the payload using the table above.
4. Call `POST /api/bme680/register` for each decoded packet.
5. Publish the readings as additional sensor channels in its existing MQTT
   telemetry messages, keyed by the source node's BT MAC.

The C3 nodes advertise independently and accumulate data even before the CAM
receiver is implemented.

---

## Current limitations

- Gas resistance is only valid once the heater has stabilised. The `gas_valid`
  flag (bit1 of the Flags byte) must be set before trusting the value.
- The `SET_CONFIG` command path is not wired through BLE; runtime reconfiguration
  will require a separate mechanism (e.g. a BLE GATT characteristic) in a future
  revision.
