from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.bme680 import router as bme680_router
from .api.commands import router as commands_router
from .api.commissioning import router as commissioning_router
from .api.db_admin import router as db_admin_router
from .api.nodes import router as nodes_router
from .api.plots import router as plots_router
from .api.telemetry import router as telemetry_router
from .api.ws import router as ws_router
from .db import SessionLocal, init_db
from .live_bus import LiveEventBus
from .mqtt_worker import MqttWorker
from .services.command_service import CommandService
from .services.ingest_service import IngestService
from .services.status_service import StatusService
from .settings import get_settings


async def _command_timeout_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(5)
        with SessionLocal() as db:
            timed_out_ids = app.state.command_service.mark_timed_out(db)
        for command_id in timed_out_ids:
            await app.state.live_bus.broadcast(
                {
                    "type": "command",
                    "status": "timeout",
                    "command_id": command_id,
                }
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    loop = asyncio.get_running_loop()
    init_db()

    live_bus = LiveEventBus()
    status_service = StatusService(
        green_max=settings.status_green_max_seconds,
        yellow_max=settings.status_yellow_max_seconds,
    )
    ingest_service = IngestService(SessionLocal, live_bus, loop=loop)
    mqtt_worker = MqttWorker(ingest_service)
    command_service = CommandService(publisher=mqtt_worker)

    app.state.live_bus = live_bus
    app.state.status_service = status_service
    app.state.ingest_service = ingest_service
    app.state.mqtt_worker = mqtt_worker
    app.state.command_service = command_service

    mqtt_worker.start()
    timeout_task = asyncio.create_task(_command_timeout_loop(app))

    try:
        yield
    finally:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass
        mqtt_worker.stop()


app = FastAPI(title="Sensor Network Dashboard API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nodes_router)
app.include_router(telemetry_router)
app.include_router(plots_router)
app.include_router(commands_router)
app.include_router(commissioning_router)
app.include_router(db_admin_router)
app.include_router(ws_router)
app.include_router(bme680_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
