from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class NodeStatusResult:
    state: str
    intensity: float
    age_seconds: float | None


class StatusService:
    def __init__(self, green_max: int = 15, yellow_max: int = 60) -> None:
        self.green_max = max(1, green_max)
        self.yellow_max = max(self.green_max + 1, yellow_max)

    def compute(self, last_seen: datetime | None, now: datetime | None = None) -> NodeStatusResult:
        if last_seen is None:
            return NodeStatusResult(state="unknown", intensity=0.3, age_seconds=None)

        last_seen = self._to_utc(last_seen)
        if now is None:
            now = datetime.now(timezone.utc)
        else:
            now = self._to_utc(now)
        age = max(0.0, (now - last_seen).total_seconds())

        if age < self.green_max:
            progress = age / self.green_max
            return NodeStatusResult(state="green", intensity=1.0 - 0.7 * progress, age_seconds=age)

        if age < self.yellow_max:
            span = self.yellow_max - self.green_max
            progress = (age - self.green_max) / span
            return NodeStatusResult(state="yellow", intensity=1.0 - 0.7 * progress, age_seconds=age)

        red_span = max(1.0, float(self.yellow_max))
        progress = min(1.0, (age - self.yellow_max) / red_span)
        return NodeStatusResult(state="red", intensity=max(0.3, 1.0 - 0.7 * progress), age_seconds=age)

    def _to_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
