from __future__ import annotations

import asyncio

from scripts.e2e_demo_simulation import run_simulation


def test_e2e_demo_simulation_flags_open_orders_and_terminal_rejections(tmp_path):
    result = asyncio.run(run_simulation(100, 42, f"sqlite:///{tmp_path / 'demo.db'}"))
    assert result["status"] == "attention"
    assert result["orders_requested"] == 100
    assert result["unique_client_order_ids"] + result["fault_counts"]["rejected"] == 100
    assert result["result_counts"]["rejected"] == result["fault_counts"]["rejected"]
    assert result["timeout_recoveries"] == 7
    assert result["fallback_cancel_status"] == "success"
    assert result["native_oco_mode"] == "native_oco"
    assert result["native_oco_protections"] == 2
    assert result["consistent"] is True
    assert result["reconciliation"]["status"] == "attention"
    assert result["reconciliation"]["unresolved_order_intents"]
    assert result["engine_preflight"] == "blocked"
    assert result["orders_sent_to_real_broker"] == 0
