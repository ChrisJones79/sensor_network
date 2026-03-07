from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import Bme680BurnIn, Bme680Sensor, Bme680WarmUp
from ..schemas import (
    Bme680BurnInResponse,
    Bme680RegisterRequest,
    Bme680RegisterResponse,
    Bme680SensorDetail,
    Bme680SensorSummary,
    Bme680WarmUpResponse,
)

router = APIRouter(prefix="/api/bme680", tags=["bme680"])

BURN_IN_HOURS = 48.0
# If a burn-in was interrupted with less than this much accumulated time, we
# silently restart rather than flagging retry_needed (avoids noise from very
# brief test sessions).
MIN_MEANINGFUL_HOURS = 0.5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _latest_burnin(db: Session, uid: str) -> Bme680BurnIn | None:
    return db.scalars(
        select(Bme680BurnIn)
        .where(Bme680BurnIn.uid == uid)
        .order_by(Bme680BurnIn.id.desc())
        .limit(1)
    ).first()


def _active_warmup(db: Session, uid: str) -> Bme680WarmUp | None:
    return db.scalars(
        select(Bme680WarmUp)
        .where(Bme680WarmUp.uid == uid, Bme680WarmUp.completed == False)  # noqa: E712
        .order_by(Bme680WarmUp.id.desc())
        .limit(1)
    ).first()


def _burnin_to_schema(b: Bme680BurnIn) -> Bme680BurnInResponse:
    return Bme680BurnInResponse(
        id=b.id,
        uid=b.uid,
        burn_in_successful=b.burn_in_successful,
        in_progress=b.in_progress,
        start_time=b.start_time,
        end_time=b.end_time,
        hours_elapsed=b.hours_elapsed,
        retry_needed=b.retry_needed,
        last_telemetry_at=b.last_telemetry_at,
    )


def _warmup_to_schema(w: Bme680WarmUp) -> Bme680WarmUpResponse:
    return Bme680WarmUpResponse(
        id=w.id,
        uid=w.uid,
        power_on_ts=w.power_on_ts,
        warm_up_complete_ts=w.warm_up_complete_ts,
        completed=w.completed,
    )


def _process_registration(
    db: Session,
    uid: str,
    sid: str,
    node_id: str,
    warming_up: bool,
) -> Bme680RegisterResponse:
    """
    Core state machine for BME680 registration.  Called on every observation
    from the network.  Idempotent for repeated calls with the same state.

    Burn-in state transitions:
      new sensor          → create catalog + start burn-in
      active burn-in + warming_up (reboot) + meaningful hours
                          → mark attempt interrupted (retry_needed), start new
      active burn-in + warming_up (reboot) + trivial hours
                          → restart burn-in in place (reset start_time)
      failed attempt + warming_up
                          → start new burn-in attempt
      active burn-in + 48 h elapsed
                          → mark successful

    Warm-up transitions (only after burn-in is successful):
      warming_up=True  + no active warm-up → open new warm-up event
      warming_up=False + active warm-up    → close warm-up event
    """
    now = _utcnow()

    # ------------------------------------------------------------------ #
    # 1. Upsert catalog entry                                             #
    # ------------------------------------------------------------------ #
    sensor = db.get(Bme680Sensor, uid)
    is_new = sensor is None
    if is_new:
        sensor = Bme680Sensor(
            uid=uid,
            sid=sid,
            node_id=node_id,
            first_seen=now,
            last_seen=now,
        )
        db.add(sensor)
        db.flush()
    else:
        sensor.sid = sid
        sensor.node_id = node_id
        sensor.last_seen = now

    # ------------------------------------------------------------------ #
    # 2. Fetch current burn-in state                                      #
    # ------------------------------------------------------------------ #
    burnin = _latest_burnin(db, uid)
    already_successful = burnin is not None and burnin.burn_in_successful

    # ------------------------------------------------------------------ #
    # 3. Burn-in state machine (skipped once successful)                  #
    # ------------------------------------------------------------------ #
    if not already_successful:
        if burnin is None:
            # First time we have ever seen this sensor.
            burnin = Bme680BurnIn(uid=uid, start_time=now, in_progress=True)
            db.add(burnin)
            db.flush()

        elif burnin.in_progress and warming_up and not is_new:
            # Sensor rebooted while a burn-in was active.
            if burnin.hours_elapsed >= MIN_MEANINGFUL_HOURS:
                # Meaningful progress — mark attempt as interrupted and start fresh.
                burnin.in_progress = False
                burnin.retry_needed = True
                burnin.end_time = now
                burnin = Bme680BurnIn(uid=uid, start_time=now, in_progress=True)
                db.add(burnin)
                db.flush()
            else:
                # Trivial session — just reset the start time in place.
                burnin.start_time = now
                burnin.hours_elapsed = 0.0
                burnin.last_telemetry_at = None

        elif not burnin.in_progress and not burnin.burn_in_successful and warming_up:
            # Previous attempt failed; sensor now powering back on for a retry.
            burnin = Bme680BurnIn(uid=uid, start_time=now, in_progress=True)
            db.add(burnin)
            db.flush()

        # Update elapsed hours for the active attempt.
        if burnin.in_progress:
            burnin.last_telemetry_at = now
            burnin.hours_elapsed = round(
                (now - burnin.start_time).total_seconds() / 3600.0, 3
            )
            if burnin.hours_elapsed >= BURN_IN_HOURS:
                burnin.burn_in_successful = True
                burnin.in_progress = False
                burnin.end_time = now
                already_successful = True

    # ------------------------------------------------------------------ #
    # 4. Warm-up tracking (only after burn-in is complete)                #
    # ------------------------------------------------------------------ #
    active_wu = _active_warmup(db, uid) if already_successful else None

    if already_successful:
        if warming_up and active_wu is None:
            # New power-on warm-up event.
            wu = Bme680WarmUp(uid=uid, power_on_ts=now)
            db.add(wu)
            active_wu = wu
        elif not warming_up and active_wu is not None:
            # Warm-up period has ended.
            active_wu.warm_up_complete_ts = now
            active_wu.completed = True
            active_wu = None

    db.commit()

    return Bme680RegisterResponse(
        uid=uid,
        is_new=is_new,
        burn_in_successful=burnin.burn_in_successful if burnin else False,
        burn_in_in_progress=burnin.in_progress if burnin else False,
        hours_elapsed=burnin.hours_elapsed if burnin else 0.0,
        retry_needed=burnin.retry_needed if burnin else False,
        warm_up_active=active_wu is not None,
    )


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #

@router.post("/register", response_model=Bme680RegisterResponse)
def register_bme680(req: Bme680RegisterRequest, db: Session = Depends(get_db)) -> Bme680RegisterResponse:
    """
    Register or update a BME680 sensor sighting.

    Called by the ESP32-CAM each time it decodes a BLE advertisement from a
    C3 sensor node, or by any other gateway that observes a BME680.  Safe to
    call on every telemetry cycle — state transitions are idempotent for
    repeated identical inputs.
    """
    uid = req.uid.lower()
    return _process_registration(db, uid, req.sid, req.node_id, req.warming_up)


@router.get("", response_model=list[Bme680SensorSummary])
def list_bme680_sensors(db: Session = Depends(get_db)) -> list[Bme680SensorSummary]:
    """Return summary for every BME680 chip in the catalog."""
    sensors = db.scalars(select(Bme680Sensor).order_by(Bme680Sensor.first_seen.asc())).all()
    results: list[Bme680SensorSummary] = []

    for s in sensors:
        burnin = _latest_burnin(db, s.uid)
        wu_count = db.scalar(
            select(Bme680WarmUp).where(Bme680WarmUp.uid == s.uid).with_only_columns(
                Bme680WarmUp.id
            ).order_by()
        )
        # Count warm-up rows
        from sqlalchemy import func
        wu_count = db.scalar(
            select(func.count()).select_from(Bme680WarmUp).where(Bme680WarmUp.uid == s.uid)
        ) or 0

        results.append(
            Bme680SensorSummary(
                uid=s.uid,
                sid=s.sid,
                node_id=s.node_id,
                first_seen=s.first_seen,
                last_seen=s.last_seen,
                burn_in_successful=burnin.burn_in_successful if burnin else False,
                burn_in_in_progress=burnin.in_progress if burnin else False,
                hours_elapsed=burnin.hours_elapsed if burnin else 0.0,
                retry_needed=burnin.retry_needed if burnin else False,
                warm_up_count=wu_count,
            )
        )

    return results


@router.get("/{uid}", response_model=Bme680SensorDetail)
def get_bme680_sensor(uid: str, db: Session = Depends(get_db)) -> Bme680SensorDetail:
    """Return full history (all burn-in attempts and warm-up events) for one sensor."""
    uid = uid.lower()
    sensor = db.get(Bme680Sensor, uid)
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"BME680 UID '{uid}' not found")

    burn_ins = db.scalars(
        select(Bme680BurnIn).where(Bme680BurnIn.uid == uid).order_by(Bme680BurnIn.id.asc())
    ).all()
    warm_ups = db.scalars(
        select(Bme680WarmUp).where(Bme680WarmUp.uid == uid).order_by(Bme680WarmUp.id.asc())
    ).all()

    return Bme680SensorDetail(
        uid=sensor.uid,
        sid=sensor.sid,
        node_id=sensor.node_id,
        first_seen=sensor.first_seen,
        last_seen=sensor.last_seen,
        burn_ins=[_burnin_to_schema(b) for b in burn_ins],
        warm_ups=[_warmup_to_schema(w) for w in warm_ups],
    )
