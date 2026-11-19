import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.manager import TradingManager
from core.reconciliation import OrderReconciler
from database_manager import DatabaseManager
from execution.live_authorization import restore_persisted_kill_state
from execution.mainnet_adapter import MainnetDisabledError
from infra.intent_identity import IntentIdempotencyConflict
from tests.test_control_plane_safety import configuration, raw_mainnet


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path}/review.db")
    manager.create_tables()
    try:
        yield manager
    finally:
        manager.engine.dispose()


def transport_adapter(session):
    adapter = raw_mainnet()
    adapter.settings.BINANCE_RECV_WINDOW_MS = 5000
    adapter.settings.BINANCE_TIMEOUT_SECONDS = 1
    adapter.api_key = "fake-test-key"
    adapter.base_url = "https://api.binance.com/api"
    adapter._timestamp = lambda: 1
    adapter._signed_query = lambda _: "mock-query-no-credentials"
    adapter.session = session
    adapter.http_client = SimpleNamespace(request=AsyncMock())
    return adapter


def test_kill_toggle_inside_to_thread_blocks_legacy_transport(monkeypatch):
    session = SimpleNamespace(request=AsyncMock())
    adapter = transport_adapter(session)
    async def delayed_worker(function, *args, **kwargs):
        adapter.settings.LIVE_KILL_SWITCH = True
        return function(*args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", delayed_worker)
    async def run():
        with pytest.raises(MainnetDisabledError):
            await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock"}, signed=True)
    asyncio.run(run())
    session.request.assert_not_called()


def test_async_transport_hook_blocks_toggle_after_signing():
    adapter = transport_adapter(None)
    def sign(_):
        adapter.settings.LIVE_KILL_SWITCH = True
        return "mock-query"
    adapter._signed_query = sign
    async def run():
        with pytest.raises(MainnetDisabledError):
            await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock"}, signed=True)
    asyncio.run(run())
    adapter.http_client.request.assert_not_awaited()


def test_unsigned_mainnet_post_never_reaches_transport():
    adapter = transport_adapter(None)
    async def run():
        with pytest.raises(MainnetDisabledError, match="assinado"):
            await adapter._request("POST", "/v3/order", {"newClientOrderId": "mock"}, signed=False)
    asyncio.run(run())
    adapter.http_client.request.assert_not_awaited()


def test_durable_kill_restores_after_database_reopen(db):
    db.record_kill_switch("default_account", True, "test-kill", "test-admin")
    db.engine.dispose()
    reopened = DatabaseManager(str(db.engine.url))
    try:
        settings = configuration(LIVE_KILL_SWITCH=False)
        result = restore_persisted_kill_state(settings, reopened, "default_account")
        assert settings.LIVE_KILL_SWITCH is True and result["restore_status"] == "kill_state_loaded"
    finally:
        reopened.engine.dispose()


def test_missing_or_failed_kill_read_never_rearms_live():
    def failed(_):
        raise RuntimeError("fake-private-message-not-for-output")
    for store in [SimpleNamespace(), SimpleNamespace(get_latest_kill_switch=failed), SimpleNamespace(get_latest_kill_switch=lambda _: {"enabled": False})]:
        settings = configuration(LIVE_KILL_SWITCH=False)
        result = restore_persisted_kill_state(settings, store, "default_account")
        assert settings.LIVE_KILL_SWITCH is True
        assert "fake-private-message" not in str(result)


def test_kill_is_local_and_durable_before_remote_await(db):
    settings = configuration()
    async def remote(_):
        assert settings.LIVE_KILL_SWITCH is True
        assert db.get_latest_kill_switch("default_account")["enabled"] is True
        return {"status": "mock-cancel-only"}
    manager = SimpleNamespace(settings=settings, db_manager=db, reconciler=SimpleNamespace(account_id="default_account"),
                              exchange_connector=SimpleNamespace(trigger_kill_switch=remote))
    assert asyncio.run(TradingManager.trigger_kill_switch(manager, "mock"))["status"] == "mock-cancel-only"


def test_failed_kill_write_stays_locally_blocked_without_remote_request():
    def failed(*_):
        raise RuntimeError("fake-secret-message")
    settings = configuration()
    remote = AsyncMock()
    manager = SimpleNamespace(settings=settings, db_manager=SimpleNamespace(record_kill_switch=failed),
                              reconciler=None, exchange_connector=SimpleNamespace(trigger_kill_switch=remote))
    with pytest.raises(RuntimeError, match="bloqueio local permanece") as error:
        asyncio.run(TradingManager.trigger_kill_switch(manager, "mock"))
    assert "fake-secret-message" not in str(error.value)
    assert settings.LIVE_KILL_SWITCH is True
    remote.assert_not_awaited()


def test_same_client_id_different_payload_or_account_is_conflict_without_send(db):
    order = {"symbol": "BTC/USDT", "action": "buy", "quantity": 1, "price": 100}
    db.reserve_order_intent("account-a", "client-reused", order)
    db.update_order_intent("client-reused", status="filled")
    with pytest.raises(IntentIdempotencyConflict):
        db.reserve_order_intent("account-b", "client-reused", order)
    changed = {**order, "symbol": "ETH/USDT", "action": "sell", "quantity": 999, "price": 200}
    send = AsyncMock()
    reconciler = OrderReconciler(db, SimpleNamespace(), account_id="account-a")
    result = asyncio.run(reconciler.submit_with_retry(changed, send, "client-reused"))
    assert result["status"] == "idempotency_conflict" and "intent" not in result
    send.assert_not_awaited()
    assert db.get_order_intent("client-reused")["symbol"] == "BTC/USDT"
    repeated = db.reserve_order_intent("account-a", "client-reused", order)
    assert repeated["status"] == "filled"
