from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from SBC.schema_v1 import (  # noqa: E402
    AckRC,
    BusType,
    CmdOp,
    CommandFrame,
    K_ACK_MID,
    K_ARGS,
    K_CAPS,
    K_CFG_ID,
    K_CMD,
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
    K_TSID,
    K_TUP,
    K_TYP,
    K_VER,
    KC_CID,
    KC_Q,
    KC_TUP,
    KC_UNIT,
    KC_VAL,
    KS_CHANS,
    KS_SID,
    MsgType,
    NodeConfig,
    NodeDefaults,
    SensorSpec,
    ChannelSpec,
    config_to_args,
    cmd_to_wire,
)


def op_from_str(op: str) -> CmdOp:
    return CmdOp[op]


def build_command_wire(node_id: str, op: CmdOp, args: dict[str, Any], mid: bytes, target_sid: str | None = None) -> dict[int, Any]:
    frame = CommandFrame(
        ver=1,
        typ=MsgType.COMMAND,
        nid=node_id,
        seq=0,
        t_up_ms=0,
        mid=mid,
        op=op,
        args=args,
        target_sid=target_sid,
    )
    return cmd_to_wire(frame)


def parse_node_config(payload: dict[str, Any]) -> NodeConfig:
    defaults_raw = payload.get("defaults", {})
    defaults = NodeDefaults(
        publish_period_ms=defaults_raw.get("publish_period_ms", 5000),
        max_batch_samples=defaults_raw.get("max_batch_samples", 1),
        jitter_ms=defaults_raw.get("jitter_ms", 250),
        offline_cache=defaults_raw.get("offline_cache", False),
    )
    sensors: list[SensorSpec] = []
    for sensor in payload.get("sensors", []):
        chans = [
            ChannelSpec(cid=ch["cid"], unit=ch["unit"], qmask=ch.get("qmask"))
            for ch in sensor.get("chans", [])
        ]
        sensors.append(
            SensorSpec(
                sid=sensor["sid"],
                stype=sensor["stype"],
                bus=BusType(sensor["bus"]),
                pins=sensor["pins"],
                params=sensor.get("params", {}),
                chans=chans,
                period_ms=sensor.get("period_ms"),
            )
        )
    return NodeConfig(
        cfg_schema=payload["cfg_schema"],
        cfg_id=payload["cfg_id"],
        applies_to=payload["applies_to"],
        groups=payload.get("groups", []),
        defaults=defaults,
        sensors=sensors,
    )


__all__ = [
    "AckRC",
    "BusType",
    "CmdOp",
    "K_ACK_MID",
    "K_ARGS",
    "K_CAPS",
    "K_CFG_ID",
    "K_CMD",
    "K_DETAIL",
    "K_FW",
    "K_HW",
    "K_MID",
    "K_NID",
    "K_NET",
    "K_RC",
    "K_REBOOT",
    "K_SENSORS",
    "K_SEQ",
    "K_TSID",
    "K_TUP",
    "K_TYP",
    "K_VER",
    "KC_CID",
    "KC_Q",
    "KC_TUP",
    "KC_UNIT",
    "KC_VAL",
    "KS_CHANS",
    "KS_SID",
    "MsgType",
    "build_command_wire",
    "config_to_args",
    "op_from_str",
    "parse_node_config",
]
