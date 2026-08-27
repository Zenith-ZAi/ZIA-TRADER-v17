from __future__ import annotations

import asyncio

from config.settings import Settings
from core.reconciliation import OrderReconciler
from database_manager import DatabaseManager
from execution.oco_manager import OCOManager


class FakeExchange:
    def __init__(self):
        self.open_orders = []
        self.entry_submissions = 0
        self.counter = 0

    async def place_order(self, symbol, action, order_type, quantity, price=None, **kwargs):
        self.counter += 1
        order_id = f"exchange-{self.counter}"
        item = {
            "order_id": order_id,
            "client_order_id": kwargs.get("client_order_id"),
            "symbol": symbol,
            "action": action,
            "status": "success",
            "filled_quantity": float(quantity),
            "filled_price": float(price or 100.0),
        }
        if order_type == "market":
            self.entry_submissions += 1
        return item

    async def send_intent(self, order):
        return await self.place_order(
            order["symbol"],
            order["action"],
            order.get("order_type", "market"),
            order["quantity"],
            order.get("price"),
            client_order_id=order.get("client_order_id"),
        )

    async def get_open_orders(self):
        return list(self.open_orders)

    async def get_positions(self):
        return []

    async def cancel_order(self, order_id, symbol=None):
        return {"status": "canceled", "order_id": order_id}


def test_intent_oco_reconcile_and_restart_are_safe(tmp_path):
    settings = Settings(DATABASE_URL=f"sqlite:///{tmp_path / 'e2e.db'}")
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    exchange = FakeExchange()
    reconciler = OrderReconciler(db, exchange, max_attempts=2, base_delay_seconds=0.0)
    client_order_id = "zia_e2e_parent_001"

    async def run():
        first = await reconciler.submit_with_retry(
            {
                "symbol": "BTC/USDT",
                "action": "buy",
                "quantity": 0.1,
                "price": 100.0,
            },
            exchange.send_intent,
            client_order_id=client_order_id,
        )
        assert first["status"] == "success"
        assert first["client_order_id"] == client_order_id
        assert exchange.entry_submissions == 1

        protection = await OCOManager(exchange, db).attach_protection(
            {**first, "symbol": "BTC/USDT", "action": "buy", "filled_quantity": 0.1},
            stop_loss=95.0,
            take_profit=110.0,
            use_native_oco=False,
        )
        assert protection["status"] == "success"
        assert len(protection["protections"]) == 2

        snapshot = await reconciler.reconcile()
        assert snapshot["status"] in {"ok", "attention"}
        assert snapshot["untracked_remote_client_order_ids"] == []

        restarted = OrderReconciler(db, exchange, max_attempts=2, base_delay_seconds=0.0)
        reused = await restarted.submit_with_retry(
            {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "price": 100.0},
            exchange.send_intent,
            client_order_id=client_order_id,
        )
        assert reused["status"] == "idempotent_reuse"
        assert exchange.entry_submissions == 1

    asyncio.run(run())
