from __future__ import annotations

import asyncio
import importlib
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_main_import_does_not_construct_database_or_trading_runtime(monkeypatch):
    import core.manager
    import database_manager

    module = importlib.import_module("main")
    calls: list[str] = []

    def forbidden_database_init(self, database_url):
        calls.append("database")
        raise AssertionError("DatabaseManager must be created by ASGI lifespan, not module import")

    def forbidden_trading_init(self, settings, db_manager):
        calls.append("trading")
        raise AssertionError("TradingManager must be created by ASGI lifespan, not module import")

    monkeypatch.setattr(database_manager.DatabaseManager, "__init__", forbidden_database_init)
    monkeypatch.setattr(core.manager.TradingManager, "__init__", forbidden_trading_init)
    module = importlib.reload(module)

    assert module.app.state.runtime is None
    assert calls == []


def test_runtime_access_before_lifespan_fails_closed():
    module = importlib.import_module("main")
    module.app.state.runtime = None

    with pytest.raises(HTTPException) as raised:
        module._trading_manager()

    assert raised.value.status_code == 503
    assert raised.value.detail == "application_runtime_not_started"


def test_runtime_builds_schema_off_event_loop_and_closes_resources():
    from api.application_runtime import build_application_runtime

    caller_thread = threading.get_ident()
    events: list[tuple[str, int | None]] = []

    class FakeDatabase:
        def __init__(self, _url):
            self.engine = SimpleNamespace(dispose=lambda: events.append(("dispose", None)))

        def create_tables(self):
            events.append(("migrate", threading.get_ident()))

    class FakeManager:
        def __init__(self, _settings, _database):
            events.append(("manager", None))
            self.exchange_connector = SimpleNamespace(connect=self.connect)

        async def connect(self):
            events.append(("connect", None))

        async def stop_all(self):
            events.append(("stop_all", None))

    settings = SimpleNamespace(DATABASE_URL="postgresql://test.invalid/db")
    runtime = asyncio.run(
        build_application_runtime(
            settings,
            database_factory=FakeDatabase,
            manager_factory=FakeManager,
        )
    )

    assert [event[0] for event in events] == ["migrate", "manager", "connect"]
    assert events[0][1] != caller_thread
    asyncio.run(runtime.close())
    asyncio.run(runtime.close())
    assert [event[0] for event in events].count("stop_all") == 1
    assert [event[0] for event in events].count("dispose") == 1


def test_failed_exchange_connect_cleans_manager_and_database():
    from api.application_runtime import build_application_runtime

    events: list[str] = []

    class FakeDatabase:
        def __init__(self, _url):
            self.engine = SimpleNamespace(dispose=lambda: events.append("dispose"))

        def create_tables(self):
            events.append("migrate")

    class FakeManager:
        def __init__(self, _settings, _database):
            self.exchange_connector = SimpleNamespace(connect=self.connect)

        async def connect(self):
            events.append("connect_failed")
            raise RuntimeError("adapter unavailable")

        async def stop_all(self):
            events.append("stop_all")

    settings = SimpleNamespace(DATABASE_URL="sqlite:///runtime-test.db")

    with pytest.raises(RuntimeError, match="adapter unavailable"):
        asyncio.run(
            build_application_runtime(
                settings,
                database_factory=FakeDatabase,
                manager_factory=FakeManager,
            )
        )

    assert events == ["migrate", "connect_failed", "stop_all", "dispose"]
