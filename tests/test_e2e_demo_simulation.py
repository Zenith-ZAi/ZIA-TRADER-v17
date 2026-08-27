from __future__ import annotations

import asyncio

from scripts.e2e_demo_simulation import run_simulation


def test_e2e_demo_simulation_reconciles_100_orders(tmp_path):
    result = asyncio.run(run_simulation(100, 42, f"sqlite:///{tmp_path / 'demo.db'}"))
    assert result["status"] == "passed"
    assert result["orders_requested"] == 100
    assert result["unique_client_order_ids"] == 100
    assert result["timeout_recoveries"] == 8
    assert result["fallback_cancel_status"] == "success"
    assert result["native_oco_mode"] == "native_oco"
    assert result["native_oco_protections"] == 2
    assert result["reconciliation"]["status"] == "ok"
    assert result["orders_sent_to_real_broker"] == 0
