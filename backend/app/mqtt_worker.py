from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .settings import get_settings

logger = logging.getLogger(__name__)

try:
    import cbor2
except Exception:  # pragma: no cover
    cbor2 = None

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None


class MqttWorker:
    def __init__(self, ingest_service) -> None:
        self.settings = get_settings()
        self.ingest_service = ingest_service
        self.client = None
        self._connected = False
        self._thread_lock = threading.Lock()

    def start(self) -> None:
        if not self.settings.mqtt_enabled:
            logger.info("MQTT disabled by config")
            return
        if mqtt is None:
            logger.warning("paho-mqtt unavailable; MQTT worker disabled")
            return

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.settings.mqtt_username:
            self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, self.settings.mqtt_keepalive)
        self.client.loop_start()

    def stop(self) -> None:
        with self._thread_lock:
            if self.client is None:
                return
            self.client.loop_stop()
            self.client.disconnect()
            self._connected = False

    def publish(self, topic: str, payload: bytes) -> bool:
        with self._thread_lock:
            if self.client is None or not self._connected:
                return False
            result = self.client.publish(topic, payload=payload, qos=1)
            return result.rc == mqtt.MQTT_ERR_SUCCESS

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connected = True
        logger.info("MQTT connected: %s", reason_code)
        subscriptions = [
            "tele/+/v1",
            "stat/+/v1",
            "inv/+/v1",
            "ack/+/v1",
        ]
        for topic in subscriptions:
            client.subscribe(topic, qos=1)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self._connected = False
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        payload = self._decode(msg.payload)
        if payload is None or not isinstance(payload, dict):
            return
        try:
            self.ingest_service.ingest_wire_message(msg.topic, payload)
        except Exception:
            logger.exception("Failed to ingest MQTT message from topic %s", msg.topic)

    def _decode(self, payload: bytes) -> dict[int, Any] | None:
        if cbor2 is not None:
            try:
                return cbor2.loads(payload)
            except Exception:
                pass
        try:
            raw = json.loads(payload.decode("utf-8"))
            if isinstance(raw, dict):
                converted: dict[int, Any] = {}
                for key, value in raw.items():
                    try:
                        converted[int(key)] = value
                    except Exception:
                        continue
                return converted
        except Exception:
            logger.debug("Message payload decode failed", exc_info=True)
        return None
