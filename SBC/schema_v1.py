# schema_v1.py
# Hierarchy + message/config definitions for:
#   Desktop SBC (Python) <-> ESP32 nodes over MQTT
#
# Design:
# - Node is blank until fed SET_CONFIG (no sensor advertisement).
# - Nodes publish telemetry periodically; SBC timestamps on ingest.
# - Commands require ACK; both logged in SBC time-series DB.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Union, Literal


# ----------------------------
# Identity hierarchy
# ----------------------------

NodeId = str          # MAC-derived stable id (hashed/HMAC'd), ASCII token
SensorId = str        # stable within node (e.g. "bme280_0", "switchbank_0")
ChannelId = str       # stable within sensor (e.g. "temp", "hum", "sw3", "vbat")
GroupId = str         # network group targeting (e.g. "hvac", "kitchen", "all")


# ----------------------------
# MQTT topic hierarchy
# ----------------------------

@dataclass(frozen=True)
class TopicsV1:
    """
    Topic conventions. Keep these stable; evolve by version suffix only.
    """
    # node -> sbc
    tele_prefix: str = "tele"      # tele/<node_id>/v1
    stat_prefix: str = "stat"      # stat/<node_id>/v1  (heartbeat + inv)
    inv_prefix: str  = "inv"       # inv/<node_id>/v1   (optional separate stream)
    ack_prefix: str  = "ack"       # ack/<node_id>/v1

    # sbc -> node
    cmnd_node_prefix: str  = "cmnd/node"   # cmnd/node/<node_id>/v1
    cmnd_group_prefix: str = "cmnd/group"  # cmnd/group/<group_id>/v1
    # sensor scoped: cmnd/node/<node_id>/sensor/<sid>/v1

    version: str = "v1"

    def tele(self, nid: NodeId) -> str:
        return f"{self.tele_prefix}/{nid}/{self.version}"

    def stat(self, nid: NodeId) -> str:
        return f"{self.stat_prefix}/{nid}/{self.version}"

    def inv(self, nid: NodeId) -> str:
        return f"{self.inv_prefix}/{nid}/{self.version}"

    def ack(self, nid: NodeId) -> str:
        return f"{self.ack_prefix}/{nid}/{self.version}"

    def cmnd_node(self, nid: NodeId) -> str:
        return f"{self.cmnd_node_prefix}/{nid}/{self.version}"

    def cmnd_sensor(self, nid: NodeId, sid: SensorId) -> str:
        return f"{self.cmnd_node_prefix}/{nid}/sensor/{sid}/{self.version}"

    def cmnd_group(self, gid: GroupId) -> str:
        return f"{self.cmnd_group_prefix}/{gid}/{self.version}"

    def cmnd_group_wildcard(self) -> str:
        return f"{self.cmnd_group_prefix}/+/{self.version}"

    def cmnd_node_wildcard(self) -> str:
        return f"{self.cmnd_node_prefix}/+/{self.version}"


# ----------------------------
# CBOR envelope hierarchy (integer keys)
# ----------------------------

class MsgType(IntEnum):
    TELEMETRY = 1
    COMMAND   = 2
    ACK       = 3
    INVENTORY = 4
    EVENT     = 5  # reserved


class CmdOp(IntEnum):
    SET_CONFIG = 10
    SET_PERIOD = 11
    OTA        = 12
    REBOOT     = 13
    READ_NOW   = 14


class BusType(IntEnum):
    GPIO    = 0
    I2C     = 1
    SPI     = 2
    UART    = 3
    ONEWIRE = 4
    ADC     = 5
    CAMERA  = 6


class AckRC(IntEnum):
    OK = 0
    INVALID_SCHEMA         = -1
    WRONG_TARGET           = -2
    UNSUPPORTED_SENSOR     = -3
    INVALID_PIN            = -4
    BUS_INIT_FAIL          = -5
    STORE_FAIL             = -6
    AUTH_FAIL              = -7


# Value types allowed at the "val" field. CBOR supports them natively.
CborScalar = Union[int, float, bool, str, bytes, None]
CborValue  = Union[CborScalar, List[Any], Dict[Any, Any]]


# ----------------------------
# Config hierarchy (SBC source-of-truth)
# ----------------------------

@dataclass
class ChannelSpec:
    """
    Defines a channel contract for parsing + unit semantics.
    """
    cid: ChannelId
    unit: str                     # e.g. "C", "%RH", "V", "bool"
    qmask: Optional[int] = None   # optional: which q bits are meaningful


@dataclass
class SensorSpec:
    """
    Defines ONE logical sensor instance on a node and its wiring.
    """
    sid: SensorId
    stype: str                   # driver key, e.g. "bme280", "gpio_switch", "adc"
    bus: BusType
    pins: Dict[str, Any]         # pin assignment map (interpreted by driver)
    params: Dict[str, Any] = field(default_factory=dict)  # addr, calibration, etc.
    chans: List[ChannelSpec] = field(default_factory=list)
    period_ms: Optional[int] = None  # per-sensor publish/read period override


@dataclass
class NodeDefaults:
    """
    Node-level behavior defaults (can be overridden per sensor).
    """
    publish_period_ms: int = 5_000
    max_batch_samples: int = 1          # per channel, before publish
    jitter_ms: int = 250                # randomization for collision avoidance
    offline_cache: bool = False         # if node should buffer when broker down


@dataclass
class NodeConfig:
    """
    Full configuration document delivered to a blank node.
    """
    cfg_schema: int                    # config schema version (not CBOR envelope ver)
    cfg_id: str                        # immutable id for audit/log correlation
    applies_to: NodeId                 # must equal node nid
    groups: List[GroupId] = field(default_factory=list)
    defaults: NodeDefaults = field(default_factory=NodeDefaults)
    sensors: List[SensorSpec] = field(default_factory=list)


# ----------------------------
# Runtime hierarchy (decoded messages)
# ----------------------------

@dataclass
class ChannelSample:
    cid: ChannelId
    unit: Optional[str] = None
    val: CborValue = None
    q: Optional[int] = None           # quality bitmask
    t_up_ms: Optional[int] = None     # optional per-sample uptime timestamp


@dataclass
class SensorBlock:
    sid: SensorId
    stype: Optional[str] = None
    channels: List[ChannelSample] = field(default_factory=list)


@dataclass
class TelemetryFrame:
    ver: int
    typ: MsgType
    nid: NodeId
    seq: int
    t_up_ms: int
    mid: Optional[bytes] = None
    sensors: List[SensorBlock] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)  # optional extra fields


@dataclass
class InventoryFrame:
    ver: int
    typ: MsgType
    nid: NodeId
    seq: int
    t_up_ms: int
    mid: Optional[bytes] = None
    hw: str = ""
    fw: str = ""
    caps: List[str] = field(default_factory=list)
    net: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandFrame:
    ver: int
    typ: MsgType
    nid: NodeId               # destination node_id (target)
    seq: int                  # sbc-side sequence (optional; can be per-target)
    t_up_ms: int              # sbc may set 0; node ignores
    mid: bytes                # message id for correlation
    op: CmdOp
    args: Dict[str, Any] = field(default_factory=dict)
    target_sid: Optional[SensorId] = None
    sig: Optional[bytes] = None      # optional command auth signature


@dataclass
class AckFrame:
    ver: int
    typ: MsgType
    nid: NodeId
    seq: int
    t_up_ms: int
    mid: Optional[bytes] = None
    ack_mid: bytes = b""
    rc: AckRC = AckRC.OK
    detail: Optional[str] = None
    applied_cfg_id: Optional[str] = None
    reboot_required: Optional[bool] = None


# ----------------------------
# CBOR key mapping (wire format)
# ----------------------------
# Common header keys
K_VER   = 0
K_TYP   = 1
K_NID   = 2
K_SEQ   = 3
K_TUP   = 4
K_MID   = 5

# Telemetry keys
K_SENSORS = 10
K_META    = 11

# Sensor block keys
KS_SID   = 0
KS_STYPE = 1
KS_CHANS = 2

# Channel keys
KC_CID  = 0
KC_UNIT = 1
KC_VAL  = 2
KC_Q    = 3
KC_TUP  = 4

# Inventory keys
K_HW   = 20
K_FW   = 21
K_CAPS = 22
K_NET  = 23

# Command keys
K_CMD    = 30
K_ARGS   = 31
K_TSID   = 32
K_SIG    = 50

# Ack keys
K_ACK_MID  = 40
K_RC       = 41
K_DETAIL   = 42
K_CFG_ID   = 43
K_REBOOT   = 44


# ----------------------------
# Wire conversion helpers (dict <-> dataclass)
# ----------------------------

def tele_to_wire(t: TelemetryFrame) -> Dict[int, Any]:
    d: Dict[int, Any] = {
        K_VER: t.ver, K_TYP: int(t.typ), K_NID: t.nid, K_SEQ: t.seq, K_TUP: t.t_up_ms,
    }
    if t.mid is not None:
        d[K_MID] = t.mid
    d[K_SENSORS] = [
        {
            KS_SID: s.sid,
            **({KS_STYPE: s.stype} if s.stype else {}),
            KS_CHANS: [
                {
                    KC_CID: c.cid,
                    **({KC_UNIT: c.unit} if c.unit is not None else {}),
                    KC_VAL: c.val,
                    **({KC_Q: c.q} if c.q is not None else {}),
                    **({KC_TUP: c.t_up_ms} if c.t_up_ms is not None else {}),
                }
                for c in s.channels
            ],
        }
        for s in t.sensors
    ]
    if t.meta:
        d[K_META] = t.meta
    return d


def inv_to_wire(i: InventoryFrame) -> Dict[int, Any]:
    d: Dict[int, Any] = {
        K_VER: i.ver, K_TYP: int(i.typ), K_NID: i.nid, K_SEQ: i.seq, K_TUP: i.t_up_ms,
        K_HW: i.hw, K_FW: i.fw, K_CAPS: i.caps,
    }
    if i.mid is not None:
        d[K_MID] = i.mid
    if i.net:
        d[K_NET] = i.net
    return d


def cmd_to_wire(c: CommandFrame) -> Dict[int, Any]:
    d: Dict[int, Any] = {
        K_VER: c.ver, K_TYP: int(c.typ), K_NID: c.nid, K_SEQ: c.seq, K_TUP: c.t_up_ms, K_MID: c.mid,
        K_CMD: int(c.op), K_ARGS: c.args,
    }
    if c.target_sid is not None:
        d[K_TSID] = c.target_sid
    if c.sig is not None:
        d[K_SIG] = c.sig
    return d


def ack_to_wire(a: AckFrame) -> Dict[int, Any]:
    d: Dict[int, Any] = {
        K_VER: a.ver, K_TYP: int(a.typ), K_NID: a.nid, K_SEQ: a.seq, K_TUP: a.t_up_ms,
        K_ACK_MID: a.ack_mid, K_RC: int(a.rc),
    }
    if a.mid is not None:
        d[K_MID] = a.mid
    if a.detail is not None:
        d[K_DETAIL] = a.detail
    if a.applied_cfg_id is not None:
        d[K_CFG_ID] = a.applied_cfg_id
    if a.reboot_required is not None:
        d[K_REBOOT] = a.reboot_required
    return d


# ----------------------------
# Config -> wire (sent inside SET_CONFIG args)
# ----------------------------

def config_to_args(cfg: NodeConfig) -> Dict[str, Any]:
    """
    Human-readable keys inside args are fine; CBOR still compresses.
    If you want pure integer keys everywhere, mirror the same approach here.
    """
    return {
        "cfg_schema": cfg.cfg_schema,
        "cfg_id": cfg.cfg_id,
        "applies_to": cfg.applies_to,
        "groups": cfg.groups,
        "defaults": {
            "publish_period_ms": cfg.defaults.publish_period_ms,
            "max_batch_samples": cfg.defaults.max_batch_samples,
            "jitter_ms": cfg.defaults.jitter_ms,
            "offline_cache": cfg.defaults.offline_cache,
        },
        "sensors": [
            {
                "sid": s.sid,
                "stype": s.stype,
                "bus": int(s.bus),
                "pins": s.pins,
                "params": s.params,
                "chans": [{"cid": ch.cid, "unit": ch.unit, **({"qmask": ch.qmask} if ch.qmask is not None else {})}
                          for ch in s.chans],
                **({"period_ms": s.period_ms} if s.period_ms is not None else {}),
            }
            for s in cfg.sensors
        ],
    }