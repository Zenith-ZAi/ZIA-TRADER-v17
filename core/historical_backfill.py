"""Restartable historical backfill planning with idempotent database upserts."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping


@dataclass(frozen=True)
class BackfillProgress:
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    expected: int
    received: int
    persisted: int
    status: str


class HistoricalBackfill:
    """Fetches missing windows and persists through the existing upsert contract."""

    def __init__(
        self,
        *,
        fetch_missing: Callable[[str, str, datetime, datetime], Awaitable[list[Mapping[str, Any]]]],
        upsert_candles: Callable[[list[dict[str, Any]]], int],
        interval_seconds: int,
    ):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.fetch_missing = fetch_missing
        self.upsert_candles = upsert_candles
        self.interval_seconds = interval_seconds

    @staticmethod
    def missing_windows(existing: list[datetime], start: datetime, end: datetime, interval_seconds: int) -> list[tuple[datetime, datetime]]:
        start = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
        present = {
            value.astimezone(timezone.utc).replace(microsecond=0)
            if value.tzinfo else value.replace(tzinfo=timezone.utc, microsecond=0)
            for value in existing
        }
        step = timedelta(seconds=interval_seconds)
        missing: list[datetime] = []
        cursor = start
        while cursor <= end:
            if cursor not in present:
                missing.append(cursor)
            cursor += step
        windows: list[tuple[datetime, datetime]] = []
        for timestamp in missing:
            if not windows or timestamp - windows[-1][1] > step:
                windows.append((timestamp, timestamp))
            else:
                windows[-1] = (windows[-1][0], timestamp)
        return windows

    async def run(self, *, symbol: str, timeframe: str, existing: list[datetime], start: datetime, end: datetime) -> BackfillProgress:
        windows = self.missing_windows(existing, start, end, self.interval_seconds)
        received = 0
        persisted = 0
        for window_start, window_end in windows:
            rows = await self.fetch_missing(symbol, timeframe, window_start, window_end)
            received += len(rows)
            normalized = [dict(row) for row in rows]
            if normalized:
                persisted += await asyncio.to_thread(self.upsert_candles, normalized)
        expected = sum(max(1, int((window_end - window_start).total_seconds() // self.interval_seconds) + 1) for window_start, window_end in windows)
        status = "completed" if persisted == expected and not windows or expected == 0 else "partial"
        if not windows:
            status = "no_missing_intervals"
        return BackfillProgress(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            expected=expected,
            received=received,
            persisted=persisted,
            status=status,
        )
