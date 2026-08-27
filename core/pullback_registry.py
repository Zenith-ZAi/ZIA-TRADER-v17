from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.pullback_strategy import PullbackSignalCache


@dataclass
class _Entry:
    cache: PullbackSignalCache
    signature: tuple[Any, ...]
    kwargs_signature: tuple[tuple[str, str], ...]


class PullbackCacheRegistry:
    """Compartilha caches de Pullback e invalida dados futuros ou alterados."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}

    @staticmethod
    def _signature(data: pd.DataFrame) -> tuple[Any, ...]:
        if not isinstance(data, pd.DataFrame) or data.empty:
            return (0, None, None)
        last_timestamp = data.index[-1] if len(data.index) else None
        columns = [column for column in ("open", "high", "low", "close", "volume") if column in data.columns]
        if not columns:
            return (len(data), str(last_timestamp), None)
        normalized = data[columns].astype(float)
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(normalized, index=True).to_numpy(dtype="uint64").tobytes()
        ).hexdigest()
        return (len(data), str(last_timestamp), digest)

    @staticmethod
    def _kwargs_signature(kwargs: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(key), str(value)) for key, value in kwargs.items()))

    def get(self, symbol: str, timeframe: str, data: pd.DataFrame, **kwargs: Any) -> PullbackSignalCache:
        key = (str(symbol).upper(), str(timeframe))
        signature = self._signature(data)
        kwargs_signature = self._kwargs_signature(kwargs)
        entry = self._entries.get(key)
        if entry and entry.signature == signature and entry.kwargs_signature == kwargs_signature:
            return entry.cache
        cache = PullbackSignalCache(data, **kwargs)
        self._entries[key] = _Entry(cache, signature, kwargs_signature)
        return cache

    def latest_signal(self, symbol: str, timeframe: str, data: pd.DataFrame, **kwargs: Any):
        cache = self.get(symbol, timeframe, data, **kwargs)
        return cache.at(len(data) - 1)

    def invalidate(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        if symbol is None and timeframe is None:
            self._entries.clear()
            return
        key = (str(symbol).upper(), str(timeframe))
        self._entries.pop(key, None)

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._entries), "keys": [f"{symbol}:{timeframe}" for symbol, timeframe in self._entries]}
