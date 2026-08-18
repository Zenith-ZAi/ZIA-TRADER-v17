"""Bloqueio determinístico de entradas em janelas de eventos econômicos."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class EconomicEventGuard:
    def __init__(self, events_file: str | None = None, before_seconds: int = 60, after_seconds: int = 300):
        if before_seconds < 0 or after_seconds < 0:
            raise ValueError("janelas de evento não podem ser negativas")
        self.before = timedelta(seconds=before_seconds)
        self.after = timedelta(seconds=after_seconds)
        self.events: list[dict[str, Any]] = []
        if events_file:
            path = Path(events_file)
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.events = payload if isinstance(payload, list) else payload.get("events", [])

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)

    def blocked(self, timestamp: datetime, symbol: str | None = None) -> dict[str, Any]:
        current = self._parse_timestamp(timestamp)
        if current is None:
            return {"blocked": False, "reason": "timestamp inválido"}
        for event in self.events:
            event_time = self._parse_timestamp(event.get("timestamp") or event.get("time"))
            if event_time is None:
                continue
            event_symbols = event.get("symbols") or ([event.get("symbol")] if event.get("symbol") else [])
            symbol_match = not event_symbols or symbol in event_symbols
            if symbol_match and event_time - self.before <= current <= event_time + self.after:
                return {
                    "blocked": True,
                    "reason": "janela de evento econômico",
                    "event": event.get("name") or event.get("title") or "evento sem nome",
                    "event_timestamp": event_time.isoformat(),
                }
        return {"blocked": False, "reason": "fora de janela de evento"}
