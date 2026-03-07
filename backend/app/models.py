from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "nodes"

    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    alias: Mapped[str] = mapped_column(String(128), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    card_color_override: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NodeCardLine(Base):
    __tablename__ = "node_card_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    line_index: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(String(256), default="")
    label: Mapped[str] = mapped_column(String(128), default="")

    __table_args__ = (UniqueConstraint("node_id", "line_index", name="uq_node_line_index"),)


class NodeConfigRecord(Base):
    __tablename__ = "node_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    cfg_id: Mapped[str] = mapped_column(String(128), index=True)
    cfg_schema: Mapped[int] = mapped_column(Integer)
    config_json: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(64), default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    t_up_ms: Mapped[int] = mapped_column(Integer)
    hw: Mapped[str] = mapped_column(String(128), default="")
    fw: Mapped[str] = mapped_column(String(128), default="")
    caps: Mapped[list] = mapped_column(JSON)
    net: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TelemetryFrameRaw(Base):
    __tablename__ = "telemetry_frames_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    t_up_ms: Mapped[int] = mapped_column(Integer)
    ingest_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)


class ChannelSample(Base):
    __tablename__ = "channel_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    sid: Mapped[str] = mapped_column(String(128), index=True)
    cid: Mapped[str] = mapped_column(String(128), index=True)
    unit: Mapped[str] = mapped_column(String(64), default="")
    numeric_val: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_val: Mapped[str | None] = mapped_column(Text, nullable=True)
    bool_val: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_up_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


Index("ix_channel_samples_node_ts", ChannelSample.node_id, ChannelSample.ts)
Index("ix_channel_samples_node_sid_cid_ts", ChannelSample.node_id, ChannelSample.sid, ChannelSample.cid, ChannelSample.ts)


class CommandLog(Base):
    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mid_hex: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    op: Mapped[str] = mapped_column(String(32), index=True)
    args: Mapped[dict] = mapped_column(JSON)
    target_node_id: Mapped[str] = mapped_column(String(128), index=True)
    target_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    issued_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    timeout_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ack_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ack_rc: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AckLog(Base):
    __tablename__ = "ack_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    mid_hex: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ack_mid_hex: Mapped[str] = mapped_column(String(128), index=True)
    rc: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_cfg_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reboot_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DashboardPlotConfig(Base):
    __tablename__ = "dashboard_plot_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), unique=True, default="global")
    config_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# BME680 sensor catalog and burn-in / warm-up tracking
# ---------------------------------------------------------------------------

class Bme680Sensor(Base):
    """One row per physical BME680 chip, keyed by calibration-data CRC32."""

    __tablename__ = "bme680_sensors"

    uid: Mapped[str] = mapped_column(String(8), primary_key=True)   # 8-char hex CRC32
    sid: Mapped[str] = mapped_column(String(128), default="")        # last known sensor ID
    node_id: Mapped[str] = mapped_column(String(128), default="")    # last known node
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bme680BurnIn(Base):
    """
    One row per burn-in attempt for a given BME680.
    Multiple rows per UID are allowed; the highest id is the current state.

    State machine:
      in_progress=True,  burn_in_successful=False  → actively accumulating hours
      in_progress=False, retry_needed=True          → interrupted before 48 h
      in_progress=False, burn_in_successful=True    → completed successfully

    A new row is created each time the sensor is detected after a reboot
    that interrupted a previous in-progress attempt.
    """

    __tablename__ = "bme680_burn_ins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(ForeignKey("bme680_sensors.uid", ondelete="CASCADE"), index=True)
    burn_in_successful: Mapped[bool] = mapped_column(Boolean, default=False)
    in_progress: Mapped[bool] = mapped_column(Boolean, default=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hours_elapsed: Mapped[float] = mapped_column(Float, default=0.0)
    retry_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_telemetry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Bme680WarmUp(Base):
    """
    One row per 30-minute warm-up event after a power-on, recorded only once
    the initial 48-hour burn-in is complete.  The firmware sets warming_up=True
    for the first WARM_UP_DURATION_S seconds after each boot; the backend
    creates a record when that flag first arrives and closes it when it clears.
    """

    __tablename__ = "bme680_warm_ups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(ForeignKey("bme680_sensors.uid", ondelete="CASCADE"), index=True)
    power_on_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    warm_up_complete_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
