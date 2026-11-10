from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.routers.market import CoreSyncRequest
from core.command_manager import CoreCommandManager


class Snapshot:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def to_dict(self):
        return {"symbol": self.symbol}


class FakeFeed:
    def __init__(self):
        self.active = 0
        self.maximum_active = 0
        self.calls = []

    async def fetch_snapshot(self, symbol: str, *, limit: int):
        self.calls.append((symbol, limit))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.005)
            return Snapshot(symbol)
        finally:
            self.active -= 1


def manager_with_feed(feed: FakeFeed) -> CoreCommandManager:
    manager = object.__new__(CoreCommandManager)
    manager.settings = SimpleNamespace(SYMBOLS=["BTC/USDT"])
    manager.data_feed = feed
    return manager


def test_sync_market_bounds_fanout_to_five_and_preserves_requested_limit():
    feed = FakeFeed()
    manager = manager_with_feed(feed)
    symbols = [f"ASSET{i}/USDT" for i in range(12)]

    result = asyncio.run(manager.sync_market(symbols=symbols, limit=75))

    assert result["successful"] == len(symbols)
    assert feed.maximum_active <= CoreCommandManager.MAX_SYNC_CONCURRENCY
    assert len(feed.calls) == len(symbols)
    assert all(limit == 75 for _, limit in feed.calls)


def test_sync_market_rejects_over_limit_before_creating_fetch_tasks():
    feed = FakeFeed()
    manager = manager_with_feed(feed)

    with pytest.raises(ValueError, match="no máximo"):
        asyncio.run(manager.sync_market(symbols=[f"S{i}" for i in range(21)]))

    assert feed.calls == []


def test_sync_market_rejects_duplicate_symbols_and_invalid_limits():
    feed = FakeFeed()
    manager = manager_with_feed(feed)

    with pytest.raises(ValueError, match="duplicados"):
        asyncio.run(manager.sync_market(symbols=["BTC/USDT", "btc/usdt"]))
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(manager.sync_market(symbols=["BTC/USDT"], limit=1001))

    assert feed.calls == []


def test_core_sync_request_is_strict_and_bounded():
    assert CoreSyncRequest.model_validate({"symbols": "BTC/USDT", "limit": 100}).symbols == ["BTC/USDT"]
    with pytest.raises(ValidationError):
        CoreSyncRequest.model_validate({"symbols": [f"S{i}" for i in range(21)]})
    with pytest.raises(ValidationError):
        CoreSyncRequest.model_validate({"symbols": ["BTC", "btc"]})
    with pytest.raises(ValidationError):
        CoreSyncRequest.model_validate({"symbols": ["BTC"], "offline": "false"})
    with pytest.raises(ValidationError):
        CoreSyncRequest.model_validate({"symbols": ["BTC"], "unrecognized": True})
