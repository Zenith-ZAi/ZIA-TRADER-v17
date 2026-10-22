from __future__ import annotations

import asyncio

from core.manager import TradingManager


class _AsyncRecorder:
    def __init__(self, events: list[str], name: str):
        self.events = events
        self.name = name

    async def stop(self):
        self.events.append(f"stop:{self.name}")

    async def close(self):
        self.events.append(f"close:{self.name}")

    async def aclose(self):
        self.events.append(f"aclose:{self.name}")


class _Connector:
    def __init__(self, events: list[str]):
        self.events = events

    async def close(self):
        self.events.append("close:exchange")


def test_stopping_engines_keeps_shared_runtime_resources_open():
    events: list[str] = []
    manager = TradingManager.__new__(TradingManager)
    manager.trading_engine = _AsyncRecorder(events, "trading")
    manager.sniper_engine = _AsyncRecorder(events, "sniper")
    manager.news_processor = _AsyncRecorder(events, "news")
    manager.http_client = _AsyncRecorder(events, "http")
    manager.exchange_connector = _Connector(events)

    asyncio.run(manager.stop_engines())

    assert events == ["stop:trading", "stop:sniper"]

    asyncio.run(manager.stop_all())

    assert events == [
        "stop:trading",
        "stop:sniper",
        "stop:trading",
        "stop:sniper",
        "close:news",
        "aclose:http",
        "close:exchange",
    ]


def test_runtime_shutdown_closes_providers_even_if_engine_stop_fails():
    events: list[str] = []

    class FailingEngine(_AsyncRecorder):
        async def stop(self):
            events.append(f"stop:{self.name}")
            raise RuntimeError("engine stop failed")

    manager = TradingManager.__new__(TradingManager)
    manager.trading_engine = FailingEngine(events, "trading")
    manager.sniper_engine = _AsyncRecorder(events, "sniper")
    manager.news_processor = _AsyncRecorder(events, "news")
    manager.http_client = _AsyncRecorder(events, "http")
    manager.exchange_connector = _Connector(events)

    try:
        asyncio.run(manager.stop_all())
    except RuntimeError as exc:
        assert "Falha ao fechar" in str(exc)
    else:
        raise AssertionError("shutdown must report the failed engine cleanup")

    assert "stop:sniper" in events
    assert "close:news" in events
    assert "aclose:http" in events
    assert "close:exchange" in events
