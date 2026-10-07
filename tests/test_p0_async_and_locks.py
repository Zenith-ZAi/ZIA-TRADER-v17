from __future__ import annotations

import asyncio
import time

import httpx
import pandas as pd
import pytest

from core.pullback_registry import PullbackCacheRegistry
from infra.async_http import AsyncProviderHTTP, ProviderCircuitOpen
from infra.redis_cache import RedisCache


class FakeAsyncClient:
    def __init__(self, responses=None, error: Exception | None = None, outcomes=None):
        self.responses = list(responses or [])
        self.outcomes = list(outcomes or [])
        self.error = error
        self.calls = 0

    async def request(self, method, url, params=None, headers=None):
        self.calls += 1
        if self.error:
            raise self.error
        if self.outcomes:
            outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, httpx.Response):
                return outcome
            payload = outcome
        else:
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
        isolated = AsyncProviderHTTP(
            client=failing,
            failure_threshold=2,
            cooldown_seconds=60,
            max_retries=0,
            backoff_base_seconds=0,
            backoff_max_seconds=0,
        )
        with pytest.raises(TimeoutError):
            await isolated.get_json("fail", "https://example.test/data")
        with pytest.raises(TimeoutError):
            await isolated.get_json("fail", "https://example.test/data")
        with pytest.raises(ProviderCircuitOpen):
            await isolated.get_json("fail", "https://example.test/data")
        assert failing.calls == 2

    asyncio.run(run())


def test_async_http_retries_transient_get_but_not_post():
    flaky = FakeAsyncClient(outcomes=[TimeoutError("temporary"), {"value": 2}])
    transport = AsyncProviderHTTP(
        client=flaky,
        max_retries=1,
        failure_threshold=3,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        jitter_ratio=0,
    )

    async def run():
        result = await transport.get_json("retry", "https://example.test/data")
        assert result == {"value": 2}
        assert flaky.calls == 2
        assert transport.health("retry")["retry"]["ok"] is True

    asyncio.run(run())
    assert transport._retryable("POST", TimeoutError("write timeout")) is False
    assert transport._retry_delay(1) == 0.0


def test_async_http_retries_rate_limit_and_bounds_jitter():
    url = "https://example.test/data"
    throttled = httpx.Response(
        429,
        headers={"Retry-After": "0.001"},
        request=httpx.Request("GET", url),
    )
    client = FakeAsyncClient(outcomes=[throttled, {"value": 3}])
    transport = AsyncProviderHTTP(
        client=client,
        max_retries=1,
        failure_threshold=3,
        backoff_base_seconds=0.002,
        backoff_max_seconds=0.01,
        jitter_ratio=0.5,
    )

    async def run():
        assert await transport.get_json("rate", url) == {"value": 3}
        assert client.calls == 2

    asyncio.run(run())
    delay = transport._retry_delay(1)
    assert 0.002 <= delay <= 0.006


def test_run_sync_offloads_work_and_applies_timeout_policy():
    transport = AsyncProviderHTTP(
        client=FakeAsyncClient(),
        max_retries=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
    )

    async def run():
        heartbeat = {"ticks": 0}

        def blocking_read():
            time.sleep(0.04)
            return 7

        task = asyncio.create_task(transport.run_sync("legacy_read", blocking_read, timeout_seconds=1))
        while not task.done():
            heartbeat["ticks"] += 1
            await asyncio.sleep(0.005)
        assert await task == 7
        assert heartbeat["ticks"] >= 2

        with pytest.raises(TimeoutError):
            await transport.run_sync("slow_read", lambda: time.sleep(0.05), timeout_seconds=0.01)

        retry_transport = AsyncProviderHTTP(
            client=object(),
            max_retries=1,
            backoff_base_seconds=0,
            backoff_max_seconds=0,
        )
        attempts = {"count": 0}

        def transient_read():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("transient")
            return 8

        assert await retry_transport.run_sync("retry_read", transient_read, timeout_seconds=1) == 8
        assert attempts["count"] == 2

        deterministic_attempts = {"count": 0}

        def invalid_read():
            deterministic_attempts["count"] += 1
            raise ValueError("invalid response")

        with pytest.raises(ValueError):
            await retry_transport.run_sync("invalid_read", invalid_read, timeout_seconds=1)
        assert deterministic_attempts["count"] == 1

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


def test_pullback_registry_extends_append_only_history_incrementally():
    registry = PullbackCacheRegistry()
    data = frame(90)
    kwargs = {"ema_period": 50}
    original = registry.get("BTCUSDT", "1h", data, **kwargs)
    expanded = frame(100)
    extended = registry.get("BTCUSDT", "1h", expanded, **kwargs)
    rebuilt = PullbackCacheRegistry().get("BTCUSDT", "1h", expanded, **kwargs)

    assert extended is original
    assert len(extended.frame) == len(expanded)
    for position in range(len(data), len(expanded)):
        incremental = extended.at(position).to_dict()
        reference = rebuilt.at(position).to_dict()
        assert {key: value for key, value in incremental.items() if key != "reasons"} == {
            key: value for key, value in reference.items() if key != "reasons"
        }


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
