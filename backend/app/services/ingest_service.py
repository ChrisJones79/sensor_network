from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AckLog, ChannelSample, CommandLog, InventorySnapshot, Node, TelemetryFrameRaw
from ..schema_bridge import (
    K_ACK_MID,
    K_CAPS,
    K_CFG_ID,
    K_DETAIL,
    K_FW,
    K_HW,
    K_MID,
    K_NID,
    K_NET,
    K_RC,
    K_REBOOT,
    K_SENSORS,
    K_SEQ,
    K_TUP,
    K_TYP,
    KC_CID,
    KC_Q,
    KC_TUP,
    KC_UNIT,
    KC_VAL,
    KS_CHANS,
    KS_SID,
    MsgType,
)


class IngestService:
    def __init__(self, session_factory, live_bus, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._session_factory = session_factory
        self._live_bus = live_bus
        self._loop = loop

    def ingest_wire_message(self, topic: str, payload: dict[int, Any]) -> None:
        msg_type = int(payload.get(K_TYP, -1))
        with self._session_factory() as db:
            if msg_type == int(MsgType.TELEMETRY):
                self._handle_telemetry(db, payload)
            elif msg_type == int(MsgType.INVENTORY):
                self._handle_inventory(db, payload)
            elif msg_type == int(MsgType.ACK):
                self._handle_ack(db, payload)
            db.commit()

    def _upsert_node(self, db: Session, node_id: str) -> Node:
        node = db.get(Node, node_id)
        if node is None:
            node = Node(node_id=node_id)
            db.add(node)
            db.flush()
        return node

    def _handle_telemetry(self, db: Session, payload: dict[int, Any]) -> None:
        node_id = str(payload.get(K_NID, ""))
        if not node_id:
            return
        self._upsert_node(db, node_id)

        ingest_ts = datetime.now(timezone.utc)
        db.add(
            TelemetryFrameRaw(
                node_id=node_id,
                seq=int(payload.get(K_SEQ, 0)),
                t_up_ms=int(payload.get(K_TUP, 0)),
                ingest_ts=ingest_ts,
                raw_payload=payload,
            )
        )

        for sensor_block in payload.get(K_SENSORS, []):
            sid = str(sensor_block.get(KS_SID, ""))
            for channel in sensor_block.get(KS_CHANS, []):
                cid = str(channel.get(KC_CID, ""))
                raw_val = channel.get(KC_VAL)
                numeric_val = None
                text_val = None
                bool_val = None
                if isinstance(raw_val, bool):
                    bool_val = raw_val
                elif isinstance(raw_val, (int, float)):
                    numeric_val = float(raw_val)
                elif raw_val is not None:
                    text_val = str(raw_val)
                sample = ChannelSample(
                    ts=ingest_ts,
                    node_id=node_id,
                    sid=sid,
                    cid=cid,
                    unit=str(channel.get(KC_UNIT, "")),
                    numeric_val=numeric_val,
                    text_val=text_val,
                    bool_val=bool_val,
                    q=channel.get(KC_Q),
                    t_up_ms=channel.get(KC_TUP),
                )
                db.add(sample)

        self._schedule_broadcast(
            {
                "type": "telemetry",
                "node_id": node_id,
                "ts": ingest_ts.isoformat(),
            }
        )

    def _handle_inventory(self, db: Session, payload: dict[int, Any]) -> None:
        node_id = str(payload.get(K_NID, ""))
        if not node_id:
            return
        self._upsert_node(db, node_id)

        snap = InventorySnapshot(
            node_id=node_id,
            seq=int(payload.get(K_SEQ, 0)),
            t_up_ms=int(payload.get(K_TUP, 0)),
            hw=str(payload.get(K_HW, "")),
            fw=str(payload.get(K_FW, "")),
            caps=payload.get(K_CAPS, []),
            net=payload.get(K_NET, {}),
            received_at=datetime.now(timezone.utc),
        )
        db.add(snap)

        self._schedule_broadcast(
            {
                "type": "inventory",
                "node_id": node_id,
                "ts": snap.received_at.isoformat(),
            }
        )

    def _handle_ack(self, db: Session, payload: dict[int, Any]) -> None:
        node_id = str(payload.get(K_NID, ""))
        if not node_id:
            return
        self._upsert_node(db, node_id)

        ack_mid = payload.get(K_ACK_MID, b"")
        if isinstance(ack_mid, bytes):
            ack_mid_hex = ack_mid.hex()
        else:
            ack_mid_hex = str(ack_mid)

        mid = payload.get(K_MID)
        mid_hex = mid.hex() if isinstance(mid, bytes) else (str(mid) if mid is not None else None)
        rc = int(payload.get(K_RC, 0))

        row = AckLog(
            node_id=node_id,
            mid_hex=mid_hex,
            ack_mid_hex=ack_mid_hex,
            rc=rc,
            detail=payload.get(K_DETAIL),
            applied_cfg_id=payload.get(K_CFG_ID),
            reboot_required=payload.get(K_REBOOT),
            ts=datetime.now(timezone.utc),
        )
        db.add(row)

        cmd = db.scalars(select(CommandLog).where(CommandLog.mid_hex == ack_mid_hex)).first()
        if cmd is not None:
            cmd.status = "ok" if rc == 0 else "fail"
            cmd.ack_ts = row.ts
            cmd.ack_detail = row.detail
            cmd.ack_rc = rc

        self._schedule_broadcast(
            {
                "type": "command",
                "node_id": node_id,
                "ack_mid_hex": ack_mid_hex,
                "status": "ok" if rc == 0 else "fail",
                "rc": rc,
            }
        )

    def _schedule_broadcast(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            asyncio.create_task(self._live_bus.broadcast(event))
            return
        asyncio.run_coroutine_threadsafe(self._live_bus.broadcast(event), loop)



def latest_node_seen_ts(db: Session, node_id: str) -> datetime | None:
    tele_ts = db.scalar(select(func.max(ChannelSample.ts)).where(ChannelSample.node_id == node_id))
    inv_ts = db.scalar(select(func.max(InventorySnapshot.received_at)).where(InventorySnapshot.node_id == node_id))
    ack_ts = db.scalar(select(func.max(AckLog.ts)).where(AckLog.node_id == node_id))
    values = [ts for ts in [tele_ts, inv_ts, ack_ts] if ts is not None]
    if not values:
        return None
    return max(values)
