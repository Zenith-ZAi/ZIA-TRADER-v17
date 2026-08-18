import json
from datetime import datetime, timezone

from core.event_guard import EconomicEventGuard
from core.pullback_strategy import calculate_pullback_signal
from execution.friction import ExecutionFriction


def test_execution_friction_is_deterministic_and_directional():
    friction = ExecutionFriction(enabled=True, seed=7)
    result = friction.apply("buy", 100.0, 2.0, spread_price=0.10, tick_size=0.01)
    assert result.executed_price > 100.10
    assert result.commission == result.executed_price * 2.0 * 0.0005


def test_event_guard_blocks_configured_window(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps([{"name": "CPI", "timestamp": "2026-08-18T12:00:00Z", "symbols": ["BTC/USDT"]}]), encoding="utf-8")
    guard = EconomicEventGuard(str(path), before_seconds=60, after_seconds=300)
    blocked = guard.blocked(datetime(2026, 8, 18, 12, 2, tzinfo=timezone.utc), "BTC/USDT")
    open_window = guard.blocked(datetime(2026, 8, 18, 12, 7, tzinfo=timezone.utc), "BTC/USDT")
    assert blocked["blocked"] is True
    assert open_window["blocked"] is False


def test_pullback_requires_long_history():
    signal = calculate_pullback_signal(None)
    assert signal.action == "hold"
    assert signal.valid is False
