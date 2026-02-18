from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path



def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    db_path: Path

    mqtt_enabled: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_keepalive: int

    command_timeout_seconds: int
    status_green_max_seconds: int
    status_yellow_max_seconds: int

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    db_path = Path(os.getenv("DB_PATH", "backend/sensor_network.db"))
    if not db_path.is_absolute():
        db_path = (root / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        db_path=db_path,
        mqtt_enabled=_get_bool("MQTT_ENABLED", True),
        mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_username=os.getenv("MQTT_USERNAME", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        mqtt_keepalive=int(os.getenv("MQTT_KEEPALIVE", "60")),
        command_timeout_seconds=int(os.getenv("COMMAND_TIMEOUT_SECONDS", "10")),
        status_green_max_seconds=int(os.getenv("STATUS_GREEN_MAX_SECONDS", "15")),
        status_yellow_max_seconds=int(os.getenv("STATUS_YELLOW_MAX_SECONDS", "60")),
    )
