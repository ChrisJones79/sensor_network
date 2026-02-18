# Backend (FastAPI + SQLite)

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Notes

- SQLite DB file defaults to `backend/sensor_network.db`.
- MQTT ingest subscribes to `tele/+/v1`, `stat/+/v1`, `inv/+/v1`, `ack/+/v1` when `MQTT_ENABLED=true`.
- WebSocket stream is available at `/ws/live`.
