from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import CommandLog
from ..schemas import CommandCreateRequest, CommandResponse

router = APIRouter(prefix="/api", tags=["commands"])



def _to_response(row: CommandLog) -> CommandResponse:
    return CommandResponse(
        command_id=row.command_id,
        node_id=row.target_node_id,
        op=row.op,
        status=row.status,
        issued_ts=row.issued_ts,
        timeout_ts=row.timeout_ts,
        ack_ts=row.ack_ts,
        ack_detail=row.ack_detail,
        ack_rc=row.ack_rc,
    )


@router.post("/commands", response_model=CommandResponse)
def create_command(req: CommandCreateRequest, request: Request, db: Session = Depends(get_db)) -> CommandResponse:
    service = request.app.state.command_service
    row = service.create_command(db, node_id=req.node_id, op=req.op, args=req.args, target_sid=req.target_sid)
    return _to_response(row)


@router.get("/commands/{command_id}", response_model=CommandResponse)
def get_command(command_id: str, db: Session = Depends(get_db)) -> CommandResponse:
    row = db.scalars(select(CommandLog).where(CommandLog.command_id == command_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return _to_response(row)
