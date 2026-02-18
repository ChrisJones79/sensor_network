# ESP32-CAM Node Commissioning

## 1) Align network endpoints

Make sure firmware, backend, and frontend point to the same services:

- Firmware MQTT broker: `platformio.ini` (`MQTT_URI`)
- Backend MQTT broker: `backend/.env` (`MQTT_HOST`, `MQTT_PORT`)
- Frontend API base URL: `frontend/.env` (`VITE_API_BASE_URL`)

## 2) Boot node and capture Node ID

After flashing and booting, open serial monitor and copy the printed node ID:

- Log format: `Node ID: NID_...`

Use this exact `NID_...` for commissioning.

## 3) Open Commissioning UI

In the dashboard:

1. Go to the **Commissioning** tab.
2. Enter/select the node ID.
3. Fill config in **Guided Form** or **Advanced JSON**.

## 4) Validate and save config

Use buttons in this order:

1. `Validate`
2. `Save Config`

This validates payload schema and stores node config in backend DB.

## 5) Send runtime commands

Use command buttons to verify node control path:

- `READ_NOW` (immediate telemetry publish)
- `SET_PERIOD` (update publish period)
- `REBOOT`

## Current limitation

`Save + SET_CONFIG` is dispatched from backend, but current firmware responds with `unsupported_op` for `SET_CONFIG`.

So:

- Config **does save** in backend DB.
- Node-side apply for `SET_CONFIG` is **not implemented yet** in firmware.
