"""Simulação local determinística de execução e reconciliação; nunca chama um broker real."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.reconciliation import OrderReconciler
from database_manager import DatabaseManager
from execution.oco_manager import OCOManager


class DemoBroker:
    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)
        self.orders: dict[str, dict[str, Any]] = {}
        self.protections: dict[str, dict[str, Any]] = {}
        self.counter = 0
        self.balances = {"USDT": 10_000.0}
        self.faults = Counter()

    async def submit(self, intent: dict[str, Any]) -> dict[str, Any]:
        client_id = str(intent["client_order_id"])
        if client_id in self.orders:
            return {**self.orders[client_id], "status": "idempotent_reuse"}
        self.counter += 1
        roll = self.random.random()
        if roll < 0.08:
            self.faults["rejected"] += 1
            return {"status": "rejected", "reason": "simulated rejection", "client_order_id": client_id}
        if roll < 0.16:
            self.faults["timeout"] += 1
            record = self._record(intent, "open", filled_quantity=0.0)
            raise TimeoutError(f"simulated timeout after broker acceptance: {client_id}")
        if roll < 0.30:
            self.faults["partial_fill"] += 1
            quantity = float(intent["quantity"]) * 0.5
            return self._record(intent, "partially_filled", filled_quantity=quantity)
        self.faults["filled"] += 1
        return self._record(intent, "filled", filled_quantity=float(intent["quantity"]))

    def _record(self, intent: dict[str, Any], status: str, filled_quantity: float) -> dict[str, Any]:
        self.orders[str(intent["client_order_id"])] = {
            "order_id": f"demo-{self.counter}",
            "client_order_id": str(intent["client_order_id"]),
            "symbol": intent["symbol"],
            "action": intent["action"],
            "status": status,
            "filled_quantity": filled_quantity,
            "filled_price": float(intent.get("price") or 100.0),
        }
        return dict(self.orders[str(intent["client_order_id"])])

    async def get_open_orders(self):
        return [item for item in self.orders.values() if item["status"] in {"open", "partially_filled"}]

    async def get_positions(self):
        positions = []
        for item in self.orders.values():
            if item["status"] in {"filled", "partially_filled"} and item["filled_quantity"] > 0:
                positions.append({"symbol": item["symbol"], "action": item["action"], "quantity": item["filled_quantity"]})
        return positions

    async def place_protection_order(self, protection: dict[str, Any]):
        order_id = f"protection-{len(self.protections) + 1}"
        item = {**protection, "order_id": order_id, "status": "success"}
        self.protections[str(protection["client_order_id"])] = item
        return item

    async def place_order(self, symbol, action, order_type, quantity, price=None, **kwargs):
        return await self.place_protection_order({
            "symbol": symbol,
            "action": action,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": price,
            "client_order_id": kwargs.get("client_order_id", f"protection-{len(self.protections) + 1}"),
        })

    async def place_oco_orders(self, payload):
        return {"status": "unsupported", "protections": []}

    async def cancel_order(self, order_id, symbol=None):
        return {"status": "canceled", "order_id": order_id}


class NativeDemoBroker(DemoBroker):
    async def place_oco_orders(self, payload):
        parent = str(payload["parent_client_order_id"])
        protections = []
        for kind, price in (("sl", payload["stop_price"]), ("tp", payload["take_profit"])):
            client_id = f"native-{kind}-{parent}"
            item = {
                "client_order_id": client_id,
                "order_id": f"native-{kind}-{parent}",
                "symbol": payload["symbol"],
                "action": payload["action"],
                "order_type": "oco_protection",
                "quantity": payload["quantity"],
                "stop_price": price,
                "limit_price": price,
                "status": "open",
            }
            self.protections[client_id] = item
            protections.append(item)
        return {"status": "success", "protections": protections}


async def run_simulation(total_orders: int, seed: int, database_url: str) -> dict[str, Any]:
    settings = Settings(DATABASE_URL=database_url, LIVE_TRADING_ENABLED=False, LIVE_MODE=False, AUTONOMOUS_TRADING_ENABLED=False, SHADOW_MODE_ENABLED=True)
    db = DatabaseManager(database_url)
    db.create_tables()
    broker = DemoBroker(seed=seed)
    reconciler = OrderReconciler(db, broker, max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0)
    oco = OCOManager(broker, db)
    results = Counter()
    recovered = 0
    first_filled: dict[str, Any] | None = None
    fallback_parent: str | None = None
    fallback_cancel_status = "not_run"
    for index in range(max(1, int(total_orders))):
        client_id = f"demo-parent-{index:04d}"
        result = await reconciler.submit_with_retry(
            {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01, "price": 100.0},
            broker.submit,
            client_order_id=client_id,
        )
        results[str(result.get("status", "error"))] += 1
        if result.get("status") == "idempotent_recovered":
            recovered += 1
        if result.get("status") in {"success", "filled", "partially_filled", "idempotent_recovered"} and float(result.get("filled_quantity", 0.0) or 0.0) > 0:
            fill = {**result, "symbol": "BTC/USDT", "action": "buy"}
            await oco.attach_protection(fill, 95.0, 110.0, use_native_oco=False)
            if fallback_parent is None:
                fallback_parent = client_id
                cancelled = await oco.cancel_for_parent(client_id)
                fallback_cancel_status = str(cancelled.get("status", "error"))
            if first_filled is None:
                first_filled = fill

    native_oco_status = "not_run"
    native_protection_count = 0
    if first_filled is not None:
        native_broker = NativeDemoBroker(seed=seed + 1)
        native_result = await OCOManager(native_broker, db).attach_protection(
            first_filled, 95.0, 110.0, use_native_oco=True
        )
        native_oco_status = str(native_result.get("mode", "error"))
        native_protection_count = len(native_result.get("protections", []))

    reconciliation = await reconciler.reconcile()
    consistent = not reconciliation.get("untracked_remote_client_order_ids")
    return {
        "status": "passed" if consistent else "attention",
        "orders_requested": int(total_orders),
        "unique_client_order_ids": len(broker.orders),
        "result_counts": dict(results),
        "fault_counts": dict(broker.faults),
        "timeout_recoveries": recovered,
        "protection_orders": len(broker.protections),
        "fallback_cancel_status": fallback_cancel_status,
        "native_oco_mode": native_oco_status,
        "native_oco_protections": native_protection_count,
        "reconciliation": reconciliation,
        "consistent": consistent,
        "live_trading_enabled": False,
        "orders_sent_to_real_broker": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--database-url", default="sqlite:////tmp/zia_demo_e2e.db")
    parser.add_argument("--output", default="reports/e2e_demo_simulation.json")
    args = parser.parse_args()
    result = asyncio.run(run_simulation(args.orders, args.seed, args.database_url))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
