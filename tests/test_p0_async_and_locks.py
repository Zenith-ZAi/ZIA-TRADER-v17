from __future__ import annotations

import asyncio

import httpx
import pandas as pd
import pytest

from core.pullback_registry import PullbackCacheRegistry
from infra.async_http import AsyncProviderHTTP, ProviderCircuitOpen
from infra.redis_cache import RedisCache


class FakeAsyncClient:
    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = 0

    async def request(self, method, url, params=None, headers=None):
        self.calls += 1
        if self.error:
            raise self.error
        payload = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        request = httpx.Request(method, url)
        return httpx.Response(200, json=payload, request=request)

    async def aclose(self):
        return None


def frame(rows: int = 240) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series(range(rows), index=index, dtype=float) + 100.0
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0}, index=index)


def test_async_http_cache_and_circuit_breaker():
    client = FakeAsyncClient(responses=[{"value": 1}])
    transport = AsyncProviderHTTP(client=client, failure_threshold=2, cooldown_seconds=60)

    async def run():
        first = await transport.get_json("provider", "https://example.test/data", ttl_seconds=30)
        second = await transport.get_json("provider", "https://example.test/data", ttl_seconds=30)
        assert first == second == {"value": 1}
        assert client.calls == 1
        failing = FakeAsyncClient(error=TimeoutError("timeout"))
        isolated = AsyncProviderHTTP(client=failing, failure_threshold=2, cooldown_seconds=60)
        with pytest.raises(TimeoutError):
            await isolated.get_json("fail", "https://example.test/data")
        with pytest.raises(TimeoutError):
            await isolated.get_json("fail", "https://example.test/data")
        with pytest.raises(ProviderCircuitOpen):
            await isolated.get_json("fail", "https://example.test/data")

    asyncio.run(run())


def test_pullback_registry_reuses_and_invalidates_by_frame_signature():
    registry = PullbackCacheRegistry()
    data = frame()
    kwargs = {"ema_period": 50}
    first = registry.get("BTCUSDT", "1h", data, **kwargs)
    second = registry.get("BTCUSDT", "1h", data.copy(), **kwargs)
    assert first is second
    changed = data.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] += 0.25
    third = registry.get("BTCUSDT", "1h", changed, **kwargs)
    assert third is not first
    assert registry.stats()["entries"] == 1


def test_redis_fallback_lock_is_exclusive_and_released():
    cache = RedisCache("redis://127.0.0.1:63999/0")

    async def run():
        first = await cache.acquire_lock("lock:test", ttl_seconds=30, renew_seconds=1)
        assert first is not None
        second = await cache.acquire_lock("lock:test", ttl_seconds=30, renew_seconds=1)
        assert second is None
        assert await cache.renew_lock("lock:test", first.token, ttl_seconds=30) is True
        await first.release()
        third = await cache.acquire_lock("lock:test", ttl_seconds=30, renew_seconds=1)
        assert third is not None
        await third.release()

    asyncio.run(run())
