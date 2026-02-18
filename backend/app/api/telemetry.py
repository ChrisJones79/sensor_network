from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import ChannelSample
from ..schemas import TelemetryQueryRequest, TelemetryQueryResponse, TracePoint, TraceSeries

router = APIRouter(prefix="/api", tags=["telemetry"])


@router.post("/telemetry/query", response_model=TelemetryQueryResponse)
def query_telemetry(req: TelemetryQueryRequest, db: Session = Depends(get_db)) -> TelemetryQueryResponse:
    traces: list[TraceSeries] = []

    for trace in req.traces:
        rows = db.scalars(
            select(ChannelSample)
            .where(
                ChannelSample.node_id == trace.node_id,
                ChannelSample.sid == trace.sid,
                ChannelSample.cid == trace.cid,
                ChannelSample.ts >= req.start_ts,
                ChannelSample.ts <= req.end_ts,
            )
            .order_by(ChannelSample.ts.asc())
            .limit(req.max_points_per_trace)
        ).all()

        points: list[TracePoint] = []
        for row in rows:
            value = row.numeric_val
            if row.bool_val is not None:
                value = row.bool_val
            elif row.text_val is not None:
                value = row.text_val
            points.append(TracePoint(ts=row.ts, value=value))

        traces.append(
            TraceSeries(
                node_id=trace.node_id,
                sid=trace.sid,
                cid=trace.cid,
                label=trace.label or f"{trace.node_id}:{trace.sid}.{trace.cid}",
                points=points,
            )
        )

    return TelemetryQueryResponse(traces=traces)
