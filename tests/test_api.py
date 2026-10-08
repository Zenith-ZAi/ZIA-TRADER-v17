import asyncio
import importlib

import pytest
from fastapi import HTTPException

from fastapi.testclient import TestClient


def test_demo_login_and_public_user(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AUTO_START_ENGINES", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "password")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "admin")

    module = importlib.import_module("main")
    with TestClient(module.app) as client:
        health_response = client.get("/healthz")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "ok"

        token_response = client.post(
            "/token",
            data={"username": "admin", "password": "admin"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]

        user_response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert user_response.status_code == 200
        assert user_response.json() == {
            "username": "admin",
            "roles": ["admin", "trader"],
        }
        assert "password" not in user_response.json()

        dashboard_response = client.get(
            "/admin/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert dashboard_response.status_code == 200

        with client.websocket_connect(f"/ws/dashboard?token={token}") as websocket:
            runtime_status = websocket.receive_json()
            assert "runtime" in runtime_status

        # Reabrir a mesma conexão autenticada simula o ciclo de reconnect do cliente.
        with client.websocket_connect(f"/ws/dashboard?token={token}") as websocket:
            runtime_status = websocket.receive_json()
            assert "runtime" in runtime_status


def test_invalid_demo_login_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api-invalid.db'}")
    monkeypatch.setenv("AUTO_START_ENGINES", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")

    module = importlib.import_module("main")
    with TestClient(module.app) as client:
        response = client.post(
            "/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401


def test_dashboard_control_surface_is_exposed():
    import importlib

    module = importlib.import_module("main")
    paths = {getattr(route, "path", "") for route in module.app.routes}
    assert "/dashboard/status" in paths
    assert "/runtime/reload" in paths
    assert "/ws/dashboard" in paths
    assert "/api/optimize_sharpe" in paths
    assert "/status" in paths
    assert "/order" in paths
    assert "/order/confirm" in paths
    assert "/market" in paths
    assert "/logs" in paths


def test_engine_start_is_blocked_when_reconciliation_needs_attention(monkeypatch):
    module = importlib.import_module("main")

    async def connect():
        return None

    async def reconcile():
        return {"status": "attention", "order_intents_recovery_pending": ["zia-unresolved"]}

    async def should_not_start():
        raise AssertionError("engine factory must not be scheduled")

    monkeypatch.setattr(module.trading_manager.exchange_connector, "connect", connect)
    monkeypatch.setattr(module.trading_manager, "reconcile", reconcile)

    async def invoke():
        with pytest.raises(HTTPException) as raised:
            await module._start_engine("phase5-reconcile-gate", should_not_start)
        assert raised.value.status_code == 503

    asyncio.run(invoke())
    assert "phase5-reconcile-gate" not in module.engine_tasks
