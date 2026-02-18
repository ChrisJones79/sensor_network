from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeCardLineConfig(BaseModel):
    line_index: int = Field(ge=0, le=3)
    source_type: Literal["channel", "token"]
    source_ref: str = ""
    label: str = ""


class NodeProfilePatch(BaseModel):
    alias: str | None = None
    location: str | None = None
    card_color_override: str | None = None
    lines: list[NodeCardLineConfig] | None = None


class NodeCardLineValue(BaseModel):
    line_index: int
    label: str
    value: str
    source_type: str
    source_ref: str
    ts: datetime | None = None


class NodeStatus(BaseModel):
    state: Literal["green", "yellow", "red", "unknown"]
    intensity: float = Field(ge=0.0, le=1.0)
    age_seconds: float | None = None
    last_seen: datetime | None = None


class NodeCardResponse(BaseModel):
    node_id: str
    alias: str
    location: str
    card_color_override: str
    status: NodeStatus
    lines: list[NodeCardLineValue]


class ChannelDescriptor(BaseModel):
    node_id: str
    sid: str
    cid: str
    unit: str
    latest_value: float | bool | str | None
    latest_ts: datetime | None


class TraceSelector(BaseModel):
    node_id: str
    sid: str
    cid: str
    label: str | None = None


class TelemetryQueryRequest(BaseModel):
    traces: list[TraceSelector]
    start_ts: datetime
    end_ts: datetime
    max_points_per_trace: int = Field(default=5000, ge=100, le=20000)


class TracePoint(BaseModel):
    ts: datetime
    value: float | bool | str | None


class TraceSeries(BaseModel):
    node_id: str
    sid: str
    cid: str
    label: str
    points: list[TracePoint]


class TelemetryQueryResponse(BaseModel):
    traces: list[TraceSeries]


class PlotTraceConfig(BaseModel):
    node_id: str
    sid: str
    cid: str
    label: str


class PlotConfig(BaseModel):
    plot_id: str
    title: str = ""
    y_axis_label: str = ""
    live_mode: bool = True
    traces: list[PlotTraceConfig] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class DashboardPlotConfigPayload(BaseModel):
    plots: list[PlotConfig] = Field(min_length=1, max_length=3)


class CommandCreateRequest(BaseModel):
    node_id: str
    op: Literal["SET_CONFIG", "SET_PERIOD", "READ_NOW", "REBOOT"]
    args: dict[str, Any] = Field(default_factory=dict)
    target_sid: str | None = None


class CommandResponse(BaseModel):
    command_id: str
    node_id: str
    op: str
    status: Literal["pending", "ok", "fail", "timeout"]
    issued_ts: datetime
    timeout_ts: datetime
    ack_ts: datetime | None = None
    ack_detail: str | None = None
    ack_rc: int | None = None


class ChannelSpecPayload(BaseModel):
    cid: str
    unit: str
    qmask: int | None = None


class SensorSpecPayload(BaseModel):
    sid: str
    stype: str
    bus: int
    pins: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    chans: list[ChannelSpecPayload] = Field(default_factory=list)
    period_ms: int | None = None


class NodeDefaultsPayload(BaseModel):
    publish_period_ms: int = 5000
    max_batch_samples: int = 1
    jitter_ms: int = 250
    offline_cache: bool = False


class NodeConfigPayload(BaseModel):
    cfg_schema: int
    cfg_id: str
    applies_to: str
    groups: list[str] = Field(default_factory=list)
    defaults: NodeDefaultsPayload = Field(default_factory=NodeDefaultsPayload)
    sensors: list[SensorSpecPayload] = Field(default_factory=list)


class CommissioningCreateRequest(BaseModel):
    source: str = "api"
    config: NodeConfigPayload
    dispatch_set_config: bool = False


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class DBExportRequest(BaseModel):
    table: Literal[
        "nodes",
        "node_card_lines",
        "node_configs",
        "inventory_snapshots",
        "telemetry_frames_raw",
        "channel_samples",
        "command_log",
        "ack_log",
        "dashboard_plot_configs",
    ]
    format: Literal["json", "csv"] = "json"
    limit: int = Field(default=5000, ge=1, le=50000)


class DBPruneRequest(BaseModel):
    table: Literal["channel_samples", "telemetry_frames_raw", "inventory_snapshots", "ack_log", "command_log"]
    older_than: datetime


class DBStatsResponse(BaseModel):
    db_path: str
    db_size_bytes: int
    table_counts: dict[str, int]
    latest_timestamps: dict[str, datetime | None]
