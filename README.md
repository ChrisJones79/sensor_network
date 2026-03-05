# Sensor Network

An isolated sensor network dashboard running on an OrangePi 5 Ultra. ESP32 nodes publish telemetry over MQTT; the backend ingests, stores, and serves it; the frontend provides a live dashboard with plotting and node commissioning.

## Architecture

```
ESP32 nodes  -->  MQTT broker (Mosquitto)  -->  Backend (FastAPI + SQLite)  -->  Frontend (React)
                                                         |
                                              WebSocket live event bus
```

### Components

| Directory | Description |
|-----------|-------------|
| `SBC/` | Shared schema: wire format constants, dataclasses, CBOR key maps |
| `backend/` | FastAPI API server, MQTT worker, SQLite database |
| `frontend/` | React dashboard (Vite, Plotly, Axios) |
| `esp32_cam_sensor/` | ESP-IDF firmware scaffold for ESP32-CAM nodes |

### Message flow

1. Each node publishes CBOR-encoded frames to `tele/<node_id>/v1`, `inv/<node_id>/v1`, `ack/<node_id>/v1`.
2. The backend's MQTT worker decodes frames and hands them to `IngestService`, which writes to SQLite and broadcasts to any connected WebSocket clients.
3. The frontend connects to `/ws/live` and refreshes node cards and plots on events.
4. Commands (SET\_CONFIG, SET\_PERIOD, READ\_NOW, REBOOT) are dispatched via `cmnd/node/<node_id>/v1` and tracked until ACK or timeout.

---

## Backend

**Stack:** FastAPI, SQLAlchemy 2, SQLite, paho-mqtt, cbor2

### Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `backend/sensor_network.db` | SQLite file path |
| `MQTT_ENABLED` | `true` | Enable MQTT worker |
| `MQTT_HOST` | `127.0.0.1` | Broker host |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USERNAME` | _(empty)_ | Broker username |
| `MQTT_PASSWORD` | _(empty)_ | Broker password |
| `MQTT_KEEPALIVE` | `60` | Keepalive seconds |
| `COMMAND_TIMEOUT_SECONDS` | `10` | Seconds before pending command is marked timed out |
| `STATUS_GREEN_MAX_SECONDS` | `15` | Age threshold for green node status |
| `STATUS_YELLOW_MAX_SECONDS` | `60` | Age threshold for yellow node status |

### MQTT topic map

| Direction | Topic pattern | Purpose |
|-----------|--------------|---------|
| Node → SBC | `tele/<node_id>/v1` | Telemetry frames |
| Node → SBC | `inv/<node_id>/v1` | Inventory / heartbeat |
| Node → SBC | `ack/<node_id>/v1` | Command acknowledgements |
| SBC → Node | `cmnd/node/<node_id>/v1` | Node-level commands |
| SBC → Node | `cmnd/node/<node_id>/sensor/<sid>/v1` | Sensor-scoped commands |

### API surface

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/nodes` | All node cards with status and configured lines |
| PATCH | `/api/nodes/{node_id}/profile` | Update alias, location, color, display lines |
| GET | `/api/nodes/{node_id}/channels` | Latest sample per channel for a node |
| POST | `/api/telemetry/query` | Time-range query for one or more channel traces |
| GET | `/api/plots/config` | Load saved dashboard plot layout |
| POST | `/api/plots/config` | Save dashboard plot layout |
| POST | `/api/commands` | Issue a command (SET\_CONFIG, SET\_PERIOD, READ\_NOW, REBOOT) |
| GET | `/api/commands/{command_id}` | Poll command status |
| POST | `/api/commissioning/node` | Create or update a node config record |
| POST | `/api/commissioning/node/{node_id}/validate` | Validate a config without saving |
| GET | `/api/db/stats` | Table row counts, DB file size, latest timestamps |
| POST | `/api/db/export` | Export a table as JSON or CSV |
| POST | `/api/db/prune` | Delete rows older than a given timestamp |
| GET | `/health` | Liveness check |
| WS | `/ws/live` | Real-time event stream (telemetry, inventory, command, heartbeat) |

### Database tables

| Table | Description |
|-------|-------------|
| `nodes` | Node registry (alias, location, color override) |
| `node_card_lines` | Configured display lines per node card |
| `node_configs` | Config records pushed to nodes |
| `inventory_snapshots` | hw/fw/caps/net from inventory frames |
| `telemetry_frames_raw` | Raw telemetry payloads for audit |
| `channel_samples` | Parsed per-channel time-series data |
| `command_log` | Issued commands with ACK state |
| `ack_log` | All received ACK frames |
| `dashboard_plot_configs` | Saved plot workspace layout |

### Tests

```bash
cd backend
pytest tests/
```

---

## Frontend

**Stack:** React 18, TypeScript, Vite, Plotly.js, Axios

### Setup

```bash
cd frontend
npm install
```

### Run (dev)

```bash
VITE_API_BASE_URL=http://<orangepi-ip>:8000 npm run dev
```

The dev server runs on port `5173`. Set `VITE_API_BASE_URL` to point at the backend; defaults to `http://localhost:8000`.

### Build

```bash
npm run build
# output in frontend/dist/
```

Serve `dist/` with any static file server pointed at the same host as the backend.

---

## SBC schema (`SBC/schema_v1.py`)

Defines the shared wire format used by both the backend and (as a reference) the firmware:

- **Integer CBOR keys** for all envelope fields (compact over the air)
- **`MsgType`** — TELEMETRY, COMMAND, ACK, INVENTORY
- **`CmdOp`** — SET\_CONFIG, SET\_PERIOD, OTA, REBOOT, READ\_NOW
- **`BusType`** — GPIO, I2C, SPI, UART, ONEWIRE, ADC, CAMERA
- **`NodeConfig` / `SensorSpec` / `ChannelSpec`** — config document sent to blank nodes
- Wire helpers: `tele_to_wire`, `inv_to_wire`, `cmd_to_wire`, `ack_to_wire`, `config_to_args`

See `SBC/example_usage.py` for a worked example of building a config and command frame.

---

## Node commissioning

A blank node has no sensors until it receives a `SET_CONFIG` command. The typical flow:

1. Build a `NodeConfig` (see `SBC/example_usage.py` or the dashboard Commissioning tab).
2. POST to `/api/commissioning/node` with `dispatch_set_config: true`. This saves the config record and immediately dispatches a `SET_CONFIG` command over MQTT.
3. The node applies the config, stores it in flash, and publishes an ACK.
4. Subsequent telemetry frames appear under the node's channels and can be plotted.

For a step-by-step guide see `esp32_cam_sensor/COMMISSIONING.md`.

---

## Running on OrangePi 5 Ultra

Install Mosquitto and start it on the default port, then start the backend and serve the frontend build:

```bash
# Broker
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto

# Backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (serve the built dist/)
cd frontend
npm run build
npx serve dist -l 3000
```

All three services can be managed as systemd units for automatic startup on boot.