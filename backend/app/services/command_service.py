from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CommandLog
from ..schema_bridge import build_command_wire, op_from_str
from ..settings import get_settings

try:
    import cbor2
except Exception:  # pragma: no cover
    cbor2 = None


class Publisher(Protocol):
    def publish(self, topic: str, payload: bytes) -> bool: ...


class CommandService:
    def __init__(self, publisher: Publisher | None = None) -> None:
        self.settings = get_settings()
        self.publisher = publisher

    def create_command(
        self,
        db: Session,
        node_id: str,
        op: str,
        args: dict,
        target_sid: str | None = None,
    ) -> CommandLog:
        command_id = uuid.uuid4().hex
        mid = os.urandom(12)
        issued = datetime.now(timezone.utc)
        timeout_ts = issued + timedelta(seconds=self.settings.command_timeout_seconds)

        row = CommandLog(
            command_id=command_id,
            mid_hex=mid.hex(),
            op=op,
            args=args,
            target_node_id=node_id,
            target_sid=target_sid,
            status="pending",
            issued_ts=issued,
            timeout_ts=timeout_ts,
        )
        db.add(row)
        db.flush()

        op_enum = op_from_str(op)
        wire_map = build_command_wire(node_id=node_id, op=op_enum, args=args, mid=mid, target_sid=target_sid)
        payload = self._encode_payload(wire_map)
        topic = self._command_topic(node_id=node_id, target_sid=target_sid)

        if self.publisher is not None:
            published = self.publisher.publish(topic, payload)
            if not published:
                row.status = "fail"
                row.ack_detail = "MQTT publish failed"

        db.commit()
        db.refresh(row)
        return row

    def _command_topic(self, node_id: str, target_sid: str | None) -> str:
        if target_sid:
            return f"cmnd/node/{node_id}/sensor/{target_sid}/v1"
        return f"cmnd/node/{node_id}/v1"

    def _encode_payload(self, payload_map: dict[int, object]) -> bytes:
        if cbor2 is not None:
            return cbor2.dumps(payload_map)
        return str(payload_map).encode("utf-8")

    def mark_timed_out(self, db: Session) -> list[str]:
        now = datetime.now(timezone.utc)
        stmt = select(CommandLog).where(CommandLog.status == "pending", CommandLog.timeout_ts < now)
        rows = db.scalars(stmt).all()
        ids: list[str] = []
        for row in rows:
            row.status = "timeout"
            row.ack_detail = "No ACK before timeout"
            ids.append(row.command_id)
        if rows:
            db.commit()
        return ids
