from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import ChannelSample, Node, NodeCardLine
from ..schemas import ChannelDescriptor, NodeCardLineValue, NodeCardResponse, NodeProfilePatch, NodeStatus
from ..services.ingest_service import latest_node_seen_ts

router = APIRouter(prefix="/api", tags=["nodes"])



def _value_from_sample(sample: ChannelSample | None) -> tuple[str, datetime | None]:
    if sample is None:
        return ("--", None)
    if sample.bool_val is not None:
        return ("true" if sample.bool_val else "false", sample.ts)
    if sample.numeric_val is not None:
        return (f"{sample.numeric_val:g}", sample.ts)
    if sample.text_val is not None:
        return (sample.text_val, sample.ts)
    return ("--", sample.ts)



def _resolve_line(db: Session, node: Node, line: NodeCardLine, status: NodeStatus) -> NodeCardLineValue:
    label = line.label or f"Line {line.line_index + 1}"
    if line.source_type == "token":
        token = line.source_ref.strip().lower()
        if token == "status":
            return NodeCardLineValue(
                line_index=line.line_index,
                label=label,
                value=f"{status.state} ({status.intensity:.2f})",
                source_type=line.source_type,
                source_ref=line.source_ref,
                ts=status.last_seen,
            )
        if token == "age_s":
            value = "--" if status.age_seconds is None else f"{status.age_seconds:.1f}s"
            return NodeCardLineValue(
                line_index=line.line_index,
                label=label,
                value=value,
                source_type=line.source_type,
                source_ref=line.source_ref,
                ts=status.last_seen,
            )
        if token == "last_seen":
            value = "--" if status.last_seen is None else status.last_seen.strftime("%m-%d %H:%M:%S")
            return NodeCardLineValue(
                line_index=line.line_index,
                label=label,
                value=value,
                source_type=line.source_type,
                source_ref=line.source_ref,
                ts=status.last_seen,
            )
        return NodeCardLineValue(
            line_index=line.line_index,
            label=label,
            value="--",
            source_type=line.source_type,
            source_ref=line.source_ref,
            ts=status.last_seen,
        )

    parts = line.source_ref.split(".", 1)
    if len(parts) != 2:
        return NodeCardLineValue(
            line_index=line.line_index,
            label=label,
            value="--",
            source_type=line.source_type,
            source_ref=line.source_ref,
            ts=None,
        )

    sid, cid = parts
    sample = db.scalars(
        select(ChannelSample)
        .where(ChannelSample.node_id == node.node_id, ChannelSample.sid == sid, ChannelSample.cid == cid)
        .order_by(ChannelSample.ts.desc())
        .limit(1)
    ).first()
    value, ts = _value_from_sample(sample)
    return NodeCardLineValue(
        line_index=line.line_index,
        label=label,
        value=value,
        source_type=line.source_type,
        source_ref=line.source_ref,
        ts=ts,
    )


@router.get("/nodes", response_model=list[NodeCardResponse])
def list_nodes(request: Request, db: Session = Depends(get_db)) -> list[NodeCardResponse]:
    status_service = request.app.state.status_service
    rows = db.scalars(select(Node).order_by(Node.node_id.asc())).all()
    results: list[NodeCardResponse] = []

    for node in rows:
        last_seen = latest_node_seen_ts(db, node.node_id)
        computed = status_service.compute(last_seen)
        status = NodeStatus(
            state=computed.state,
            intensity=computed.intensity,
            age_seconds=computed.age_seconds,
            last_seen=last_seen,
        )

        line_rows = db.scalars(
            select(NodeCardLine).where(NodeCardLine.node_id == node.node_id).order_by(NodeCardLine.line_index.asc())
        ).all()

        if not line_rows:
            line_rows = [
                NodeCardLine(node_id=node.node_id, line_index=0, source_type="token", source_ref="status", label="Status"),
                NodeCardLine(node_id=node.node_id, line_index=1, source_type="token", source_ref="last_seen", label="Seen"),
                NodeCardLine(node_id=node.node_id, line_index=2, source_type="token", source_ref="age_s", label="Age"),
                NodeCardLine(node_id=node.node_id, line_index=3, source_type="token", source_ref="", label=""),
            ]

        lines = [_resolve_line(db, node, line, status) for line in line_rows]
        results.append(
            NodeCardResponse(
                node_id=node.node_id,
                alias=node.alias,
                location=node.location,
                card_color_override=node.card_color_override,
                status=status,
                lines=sorted(lines, key=lambda item: item.line_index),
            )
        )

    return results


@router.patch("/nodes/{node_id}/profile", response_model=NodeCardResponse)
def patch_node_profile(node_id: str, patch: NodeProfilePatch, request: Request, db: Session = Depends(get_db)) -> NodeCardResponse:
    node = db.get(Node, node_id)
    if node is None:
        node = Node(node_id=node_id)
        db.add(node)
        db.flush()

    if patch.alias is not None:
        node.alias = patch.alias
    if patch.location is not None:
        node.location = patch.location
    if patch.card_color_override is not None:
        node.card_color_override = patch.card_color_override

    if patch.lines is not None:
        db.execute(delete(NodeCardLine).where(NodeCardLine.node_id == node_id))
        for line in patch.lines:
            db.add(
                NodeCardLine(
                    node_id=node_id,
                    line_index=line.line_index,
                    source_type=line.source_type,
                    source_ref=line.source_ref,
                    label=line.label,
                )
            )

    db.commit()

    cards = list_nodes(request=request, db=db)
    for card in cards:
        if card.node_id == node_id:
            return card
    raise HTTPException(status_code=404, detail="Node not found")


@router.get("/nodes/{node_id}/channels", response_model=list[ChannelDescriptor])
def list_node_channels(node_id: str, db: Session = Depends(get_db)) -> list[ChannelDescriptor]:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    recent = db.scalars(
        select(ChannelSample).where(ChannelSample.node_id == node_id).order_by(ChannelSample.ts.desc()).limit(5000)
    ).all()

    seen: set[tuple[str, str]] = set()
    out: list[ChannelDescriptor] = []
    for sample in recent:
        key = (sample.sid, sample.cid)
        if key in seen:
            continue
        seen.add(key)
        latest_value = sample.numeric_val
        if sample.bool_val is not None:
            latest_value = sample.bool_val
        elif sample.text_val is not None:
            latest_value = sample.text_val
        out.append(
            ChannelDescriptor(
                node_id=node_id,
                sid=sample.sid,
                cid=sample.cid,
                unit=sample.unit,
                latest_value=latest_value,
                latest_ts=sample.ts,
            )
        )

    return sorted(out, key=lambda row: (row.sid, row.cid))
