from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import (
    AckLog,
    Bme680BurnIn,
    Bme680Sensor,
    Bme680WarmUp,
    ChannelSample,
    CommandLog,
    DashboardPlotConfig,
    InventorySnapshot,
    Node,
    NodeCardLine,
    NodeConfigRecord,
    TelemetryFrameRaw,
)
from ..schemas import DBExportRequest, DBPruneRequest, DBStatsResponse
from ..settings import get_settings

router = APIRouter(prefix="/api", tags=["db"])

TABLE_MAP = {
    "nodes": Node,
    "node_card_lines": NodeCardLine,
    "node_configs": NodeConfigRecord,
    "inventory_snapshots": InventorySnapshot,
    "telemetry_frames_raw": TelemetryFrameRaw,
    "channel_samples": ChannelSample,
    "command_log": CommandLog,
    "ack_log": AckLog,
    "dashboard_plot_configs": DashboardPlotConfig,
    "bme680_sensors": Bme680Sensor,
    "bme680_burn_ins": Bme680BurnIn,
    "bme680_warm_ups": Bme680WarmUp,
}

TS_COLUMN_MAP = {
    "channel_samples": ChannelSample.ts,
    "telemetry_frames_raw": TelemetryFrameRaw.ingest_ts,
    "inventory_snapshots": InventorySnapshot.received_at,
    "ack_log": AckLog.ts,
    "command_log": CommandLog.issued_ts,
}


@router.get("/db/stats", response_model=DBStatsResponse)
def get_db_stats(db: Session = Depends(get_db)) -> DBStatsResponse:
    settings = get_settings()
    db_path = Path(settings.db_path)

    counts: dict[str, int] = {}
    for name, model in TABLE_MAP.items():
        counts[name] = int(db.scalar(select(func.count()).select_from(model)) or 0)

    latest: dict[str, object] = {
        "channel_samples": db.scalar(select(func.max(ChannelSample.ts))),
        "telemetry_frames_raw": db.scalar(select(func.max(TelemetryFrameRaw.ingest_ts))),
        "inventory_snapshots": db.scalar(select(func.max(InventorySnapshot.received_at))),
        "ack_log": db.scalar(select(func.max(AckLog.ts))),
        "command_log": db.scalar(select(func.max(CommandLog.issued_ts))),
    }

    return DBStatsResponse(
        db_path=str(db_path),
        db_size_bytes=db_path.stat().st_size if db_path.exists() else 0,
        table_counts=counts,
        latest_timestamps=latest,
    )


@router.post("/db/export")
def export_data(req: DBExportRequest, db: Session = Depends(get_db)) -> dict:
    stmt = text(f"SELECT * FROM {req.table} LIMIT :limit")
    rows = [dict(r._mapping) for r in db.execute(stmt, {"limit": req.limit}).all()]

    if req.format == "json":
        return {"table": req.table, "format": "json", "rows": rows}

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else [])
    if rows:
        writer.writeheader()
        writer.writerows(rows)
    return {"table": req.table, "format": "csv", "data": output.getvalue()}


@router.post("/db/prune")
def prune_data(req: DBPruneRequest, db: Session = Depends(get_db)) -> dict:
    ts_col = TS_COLUMN_MAP.get(req.table)
    model = TABLE_MAP.get(req.table)
    if ts_col is None or model is None:
        raise HTTPException(status_code=400, detail="Unsupported prune target")

    result = db.execute(delete(model).where(ts_col < req.older_than))
    db.commit()
    return {
        "table": req.table,
        "older_than": req.older_than,
        "deleted_rows": result.rowcount or 0,
    }
