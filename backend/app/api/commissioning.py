from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import Node, NodeConfigRecord
from ..schemas import CommissioningCreateRequest, ValidationResponse
from ..schema_bridge import config_to_args, parse_node_config

router = APIRouter(prefix="/api", tags=["commissioning"])


def _validate_node_config_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        cfg = parse_node_config(payload)
        if not cfg.applies_to:
            errors.append("applies_to must be provided")
        if not cfg.cfg_id:
            errors.append("cfg_id must be provided")
        for sensor in cfg.sensors:
            if not sensor.sid:
                errors.append("sensor.sid must be provided")
            if not sensor.chans:
                errors.append(f"sensor {sensor.sid} must define at least one channel")
            for ch in sensor.chans:
                if not ch.cid:
                    errors.append(f"sensor {sensor.sid} has channel with empty cid")
    except Exception as exc:
        errors.append(str(exc))
    return (len(errors) == 0, errors)


@router.post("/commissioning/node/{node_id}/validate", response_model=ValidationResponse)
def validate_node_config(node_id: str, request: CommissioningCreateRequest) -> ValidationResponse:
    payload = request.config.model_dump()
    valid, errors = _validate_node_config_payload(payload)
    if payload.get("applies_to") != node_id:
        valid = False
        errors.append("config.applies_to must match node_id")
    return ValidationResponse(valid=valid, errors=errors)


@router.post("/commissioning/node")
def create_or_update_node_config(req: CommissioningCreateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    payload = req.config.model_dump()
    valid, errors = _validate_node_config_payload(payload)
    if not valid:
        raise HTTPException(status_code=422, detail={"errors": errors})

    node_id = payload["applies_to"]
    node = db.get(Node, node_id)
    if node is None:
        node = Node(node_id=node_id)
        db.add(node)
        db.flush()

    db.execute(update(NodeConfigRecord).where(NodeConfigRecord.node_id == node_id).values(active=False))
    row = NodeConfigRecord(
        node_id=node_id,
        cfg_id=payload["cfg_id"],
        cfg_schema=payload["cfg_schema"],
        config_json=payload,
        source=req.source,
        active=True,
    )
    db.add(row)
    db.flush()

    command = None
    if req.dispatch_set_config:
        cfg = parse_node_config(payload)
        command_service = request.app.state.command_service
        command = command_service.create_command(
            db,
            node_id=node_id,
            op="SET_CONFIG",
            args=config_to_args(cfg),
            target_sid=None,
        )

    db.commit()
    return {
        "node_id": node_id,
        "cfg_id": row.cfg_id,
        "config_record_id": row.id,
        "dispatched_command_id": command.command_id if command is not None else None,
    }
