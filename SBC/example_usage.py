# example_usage.py
from __future__ import annotations

import os
import time
from schema_v1 import (
    TopicsV1, MsgType, CmdOp, CommandFrame, NodeConfig, NodeDefaults,
    SensorSpec, ChannelSpec, BusType, config_to_args, cmd_to_wire
)

TOP = TopicsV1()

def new_mid(n: int = 12) -> bytes:
    return os.urandom(n)

# Example: build a node config for a blank ESP32 node
nid = "NID_7M4Q2K1Z9W3F"  # MAC-derived token

cfg = NodeConfig(
    cfg_schema=1,
    cfg_id="cfg-2026-02-15T22:10:00Z-kitchen-1",
    applies_to=nid,
    groups=["kitchen", "all"],
    defaults=NodeDefaults(publish_period_ms=5000, jitter_ms=250),
    sensors=[
        SensorSpec(
            sid="bme280_0",
            stype="bme280",
            bus=BusType.I2C,
            pins={"sda": 21, "scl": 22},
            params={"addr": 0x76},
            chans=[ChannelSpec("temp", "C"), ChannelSpec("hum", "%RH"), ChannelSpec("pres", "Pa")],
            period_ms=5000,
        ),
        SensorSpec(
            sid="switchbank_0",
            stype="gpio_switch",
            bus=BusType.GPIO,
            pins={"in": [32, 33, 34], "pull": "up", "invert": True},
            chans=[ChannelSpec("sw0", "bool"), ChannelSpec("sw1", "bool"), ChannelSpec("sw2", "bool")],
            period_ms=250,
        ),
    ],
)

cmd = CommandFrame(
    ver=1,
    typ=MsgType.COMMAND,
    nid=nid,
    seq=int(time.time()),
    t_up_ms=0,
    mid=new_mid(),
    op=CmdOp.SET_CONFIG,
    args=config_to_args(cfg),
)

topic = TOP.cmnd_node(nid)
payload_map = cmd_to_wire(cmd)

# Encode payload_map to CBOR with cbor2.dumps(payload_map) when you're ready to publish.
print(topic)
print(payload_map.keys())