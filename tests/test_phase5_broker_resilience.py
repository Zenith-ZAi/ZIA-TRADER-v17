from __future__ import annotations

import asyncio

from core.reconciliation import OrderReconciler
from database_manager import DatabaseManager


class FakeBroker:
    def __init__(self, remote_order=None, open_orders=None, send_result=None, send_error=None):
        self.remote_order = dict(remote_order) if remote_order else None
        self.open_orders = list(open_orders or [])
        self.send_result = dict(send_result or {"status": "success", "order_id": "ex-1", "filled_quantity": 0.1})
        self.send_error = send_error
        self.lookup_calls = []
        self.send_calls = []

    async def get_order_by_client_order_id(self, client_order_id, symbol):
        self.lookup_calls.append((client_order_id, symbol))
        if self.remote_order and self.remote_order.get("client_order_id") == client_order_id:
            return dict(self.remote_order)
        return None

    async def get_open_orders(self):
        return list(self.open_orders)

    async def get_positions(self):
        return []

    async def send(self, order):
        self.send_calls.append(dict(order))
        if self.send_error:
            raise self.send_error
        return dict(self.send_result)


def make_db(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'phase5.db'}")
    db.create_tables()
    return db


def order_data():
    return {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "price": 100.0}


def persist_submitted(db, client_order_id="zia_phase5_restart"):
    db.reserve_order_intent("default_account", client_order_id, order_data())
    db.update_order_intent(client_order_id, status="submitted", attempts=1)
    return client_order_id


def test_restart_queries_exchange_and_recovers_submitted_partial_fill(tmp_path):
    db = make_db(tmp_path)
    client_order_id = persist_submitted(db)
    broker = FakeBroker(remote_order={
        "client_order_id": client_order_id,
        "order_id": "exchange-42",
        "symbol": "BTC/USDT",
        "status": "partially_filled",
        "filled_quantity": 0.04,
    })
    restarted = OrderReconciler(db, broker, max_attempts=2, base_delay_seconds=0.0)

    result = asyncio.run(restarted.submit_with_retry(order_data(), broker.send, client_order_id))

    assert result["status"] == "idempotent_recovered"
    assert result["intent"]["status"] == "partially_filled"
    assert broker.lookup_calls == [(client_order_id, "BTC/USDT")]
    assert broker.send_calls == []


def test_restart_with_inconclusive_lookup_fails_closed_without_resubmitting(tmp_path):
    db = make_db(tmp_path)
    client_order_id = persist_submitted(db)
    broker = FakeBroker()
    restarted = OrderReconciler(db, broker, max_attempts=3, base_delay_seconds=0.0)

    result = asyncio.run(restarted.submit_with_retry(order_data(), broker.send, client_order_id))

    assert result["status"] == "recovery_pending"
    assert result["intent"]["status"] == "submitted"
    assert broker.lookup_calls == [(client_order_id, "BTC/USDT")]
    assert broker.send_calls == []


def test_reconcile_sweeps_submitted_intents_after_process_restart(tmp_path):
    db = make_db(tmp_path)
    client_order_id = persist_submitted(db, "zia_phase5_startup_reconcile")
    broker = FakeBroker(remote_order={
        "client_order_id": client_order_id,
        "order_id": "exchange-45",
        "symbol": "BTC/USDT",
        "status": "filled",
        "filled_quantity": 0.1,
    })
    restarted = OrderReconciler(db, broker)

    result = asyncio.run(restarted.reconcile())

    assert result["status"] == "ok"
    assert broker.lookup_calls == [(client_order_id, "BTC/USDT")]
    assert result["recovered_order_intents"] == [{
        "client_order_id": client_order_id,
        "status": "filled",
        "exchange_order_id": "exchange-45",
    }]
    assert db.get_order_intent(client_order_id)["status"] == "filled"


def test_reconcile_flags_unconfirmed_submitted_intents_for_operator_attention(tmp_path):
    db = make_db(tmp_path)
    client_order_id = persist_submitted(db, "zia_phase5_startup_unknown")
    broker = FakeBroker()
    restarted = OrderReconciler(db, broker)

    result = asyncio.run(restarted.reconcile())

    assert result["status"] == "attention"
    assert result["order_intents_recovery_pending"] == [client_order_id]
    assert result["local_intents_without_remote_order"] == [client_order_id]


def test_partial_fill_is_refreshed_before_duplicate_call(tmp_path):
    db = make_db(tmp_path)
    broker = FakeBroker(send_result={
        "status": "partially_filled",
        "order_id": "exchange-43",
        "filled_quantity": 0.04,
    })
    reconciler = OrderReconciler(db, broker, max_attempts=1, base_delay_seconds=0.0)
    client_order_id = "zia_phase5_partial"

    first = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))
    broker.remote_order = {
        "client_order_id": client_order_id,
        "order_id": "exchange-43",
        "symbol": "BTC/USDT",
        "status": "filled",
        "filled_quantity": 0.1,
    }
    second = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))

    assert first["intent"]["status"] == "partially_filled"
    assert second["status"] == "idempotent_recovered"
    assert second["intent"]["status"] == "filled"
    assert len(broker.send_calls) == 1
    assert len(broker.lookup_calls) == 1


def test_timeout_after_remote_acceptance_recovers_by_client_id(tmp_path):
    db = make_db(tmp_path)
    client_order_id = "zia_phase5_timeout"
    broker = FakeBroker(
        remote_order={
            "client_order_id": client_order_id,
            "order_id": "exchange-44",
            "symbol": "BTC/USDT",
            "status": "open",
            "filled_quantity": 0.0,
        },
        send_error=TimeoutError("response lost after acceptance"),
    )
    reconciler = OrderReconciler(db, broker, max_attempts=3, base_delay_seconds=0.0)

    result = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))

    assert result["status"] == "idempotent_recovered"
    assert result["intent"]["status"] == "open"
    assert len(broker.send_calls) == 1
    assert broker.lookup_calls == [(client_order_id, "BTC/USDT")]


def test_timeout_with_inconclusive_lookup_does_not_retry(tmp_path):
    db = make_db(tmp_path)
    client_order_id = "zia_phase5_unknown_timeout"
    broker = FakeBroker(send_error=TimeoutError("transport state unknown"))
    reconciler = OrderReconciler(db, broker, max_attempts=3, base_delay_seconds=0.0)

    result = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))

    assert result["status"] == "recovery_pending"
    assert result["intent"]["status"] == "submitted"
    assert len(broker.send_calls) == 1
    assert broker.lookup_calls == [(client_order_id, "BTC/USDT")]


def test_duplicate_call_after_filled_response_does_not_send_again(tmp_path):
    db = make_db(tmp_path)
    broker = FakeBroker()
    reconciler = OrderReconciler(db, broker, max_attempts=1, base_delay_seconds=0.0)
    client_order_id = "zia_phase5_duplicate"

    first = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))
    second = asyncio.run(reconciler.submit_with_retry(order_data(), broker.send, client_order_id))

    assert first["status"] == "success"
    assert second["status"] == "idempotent_reuse"
    assert len(broker.send_calls) == 1
