from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..schema_bridge import parse_node_config



def validate_node_config_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
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



def normalize_node_config(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = parse_node_config(payload)
    return asdict(cfg)
