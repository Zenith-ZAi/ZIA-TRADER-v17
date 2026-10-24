from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.application import create_app
from config.settings import Settings


EXPECTED_ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/health"),
    ("GET", "/metrics"),
    ("POST", "/token"),
    ("GET", "/users/me"),
    ("GET", "/test_rate_limit"),
    ("GET", "/users/me/items/"),
    ("GET", "/admin/dashboard"),
    ("POST", "/admin/kill-switch"),
    ("GET", "/status"),
    ("POST", "/order"),
    ("POST", "/order/confirm"),
    ("GET", "/market"),
    ("GET", "/logs"),
    ("GET", "/dashboard/status"),
    ("GET", "/core/analyze"),
    ("POST", "/core/sync"),
    ("GET", "/api/optimize_sharpe"),
    ("POST", "/runtime/reload"),
    ("WEBSOCKET", "/ws/dashboard"),
    ("GET", "/"),
    ("POST", "/trading/start"),
    ("POST", "/sniper/start"),
    ("POST", "/trading/stop"),
}


def route_contract(app) -> set[tuple[str, str]]:
    contract = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}:
            continue
        methods = getattr(route, "methods", None)
        if methods:
            contract.update((method, path) for method in methods if method not in {"HEAD", "OPTIONS"})
        elif route.__class__.__name__ == "APIWebSocketRoute":
            contract.add(("WEBSOCKET", path))
    return contract


def test_app_factory_has_isolated_state_and_preserves_route_contract():
    settings = Settings(PROJECT_NAME="Factory test", AUTO_START_ENGINES=False)
    app_a = create_app(settings)
    app_b = create_app(settings)

    assert route_contract(app_a) == EXPECTED_ROUTES
    assert route_contract(app_b) == EXPECTED_ROUTES
    assert app_a.state.runtime is None
    assert app_a.state.engine_tasks == {}
    assert app_a.state.engine_tasks is not app_b.state.engine_tasks
    assert app_a.state.settings is settings


def test_factory_defers_runtime_creation_to_lifespan_and_uses_injected_jwt_secret(monkeypatch):
    from api.dependencies import get_trader_user
    import monitoring.telemetry.telemetry_setup as telemetry_setup

    monkeypatch.setattr(telemetry_setup, "setup_telemetry", lambda *_args, **_kwargs: None)
    settings = Settings(
        PROJECT_NAME="Factory auth test",
        ENVIRONMENT="production",
        AUTH_MODE="env",
        AUTH_USERNAME="api-user",
        AUTH_PASSWORD="local-test-password",
        SECRET_KEY="factory-test-secret-key-material",
        AUTO_START_ENGINES=False,
        DEMO_AUTH_ENABLED=False,
        LIVE_KILL_SWITCH=True,
        SHADOW_MODE_ENABLED=True,
        REQUIRE_PERSISTENT_DATABASE=True,
        REQUIRE_PERSISTENT_REDIS=True,
        REQUIRE_ALEMBIC_HEAD=True,
        DATABASE_URL="postgresql+psycopg2://user:pass@localhost/db",
        REDIS_URL="redis://localhost:6379/0",
    )
    calls: list[str] = []

    class FakeRuntime:
        trading_manager = SimpleNamespace()

        async def close(self):
            calls.append("close")

    async def runtime_builder(app_settings):
        assert app_settings is settings
        calls.append("build")
        return FakeRuntime()

    app = create_app(settings, runtime_builder=runtime_builder)
    assert calls == []
    app.dependency_overrides[get_trader_user] = lambda: {
        "username": "api-user",
        "roles": ["trader", "admin"],
    }

    with TestClient(app) as client:
        assert calls == ["build"]
        assert app.state.runtime is not None
        token_response = client.post(
            "/token",
            data={"username": "api-user", "password": "local-test-password"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]
        profile = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert profile.status_code == 200
        assert profile.json() == {"username": "api-user", "roles": ["admin", "trader"]}

    assert calls == ["build", "close"]
    assert app.state.runtime is None


def test_main_import_does_not_import_trading_manager_or_torch():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import main, sys; assert 'core.manager' not in sys.modules; assert 'torch' not in sys.modules; assert main.app.state.runtime is None",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_docker_context_excludes_secret_and_generated_material():
    from pathlib import Path

    dockerignore = Path(__file__).resolve().parents[1] / ".dockerignore"
    contents = dockerignore.read_text(encoding="utf-8")
    for required_pattern in (
        "**/.env",
        "**/.env.*",
        "**/*.pem",
        "**/*.key",
        "data/*.db",
        "data/*",
        "!data/news_processor.py",
        "reports/",
        "tests/",
        "**/__pycache__/",
    ):
        assert required_pattern in contents
    assert (dockerignore.parent / "data" / "news_processor.py").is_file()


def test_concurrent_engine_start_is_serialized_per_app():
    import asyncio
    from api.runtime_services import start_engine, stop_engine_tasks

    settings = Settings(AUTO_START_ENGINES=False, SNIPER_ENABLED=False)

    class FakeExchange:
        is_connected = True

    class FakeManager:
        exchange_connector = FakeExchange()

        async def reconcile(self):
            return {"status": "ok"}

    app = create_app(settings)
    app.state.runtime = SimpleNamespace(trading_manager=FakeManager())
    started = asyncio.Event()

    async def engine_loop():
        started.set()
        await asyncio.Event().wait()

    async def run_concurrent_starts():
        results = await asyncio.gather(
            start_engine(app, "trading", engine_loop),
            start_engine(app, "trading", engine_loop),
        )
        assert sorted(results) == [False, True]
        await started.wait()
        await stop_engine_tasks(app)

    asyncio.run(run_concurrent_starts())
    assert app.state.engine_tasks == {}


def test_stop_waits_for_inflight_start_and_leaves_no_engine_task():
    import asyncio
    from api.runtime_services import start_engine, stop_engines

    settings = Settings(AUTO_START_ENGINES=False, SNIPER_ENABLED=False)
    app = create_app(settings)
    entered_reconcile = asyncio.Event()
    allow_reconcile = asyncio.Event()
    engine_started = asyncio.Event()

    class FakeExchange:
        is_connected = True

    class FakeManager:
        exchange_connector = FakeExchange()
        stopped = False

        async def reconcile(self):
            entered_reconcile.set()
            await allow_reconcile.wait()
            return {"status": "ok"}

        async def start_trading(self):
            engine_started.set()
            await asyncio.Event().wait()

        async def stop_engines(self):
            self.stopped = True

    manager = FakeManager()
    app.state.runtime = SimpleNamespace(trading_manager=manager)

    async def run_race():
        start_task = asyncio.create_task(
            start_engine(app, "trading", manager.start_trading)
        )
        await entered_reconcile.wait()
        stop_task = asyncio.create_task(stop_engines(app, manager))
        await asyncio.sleep(0)
        assert not stop_task.done()
        allow_reconcile.set()
        assert await start_task is True
        await engine_started.wait()
        await stop_task
        assert manager.stopped is True
        assert app.state.engine_tasks == {}

    asyncio.run(run_race())


def test_unsafe_production_configuration_fails_before_runtime_builder():
    import pytest

    settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="dev-only-change-me",
        AUTH_MODE="env",
        AUTH_USERNAME="api-user",
        AUTH_PASSWORD="local-test-password",
    )
    builder_calls = []

    async def runtime_builder(_settings):
        builder_calls.append("called")
        return SimpleNamespace(trading_manager=SimpleNamespace(), close=lambda: None)

    app = create_app(settings, runtime_builder=runtime_builder)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        with TestClient(app):
            pass
    assert builder_calls == []
