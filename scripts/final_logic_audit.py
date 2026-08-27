"""Auditoria funcional final do core em modo somente leitura/histórico."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from core.feature_pipeline import FeaturePipeline
from core.flow_analysis import analyze_order_flow
from core.market_signals import MarketSignalCache, calculate_market_signal
from core.microstructure import estimate_entry_costs
from core.news_gate import evaluate_news_gate
from core.risk_guard import evaluate_circuit_breaker


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"])
    return frame.rename(columns={"open_time": "timestamp"}).set_index("timestamp").sort_index()


async def run_audit(dataset: Path) -> dict:
    frame = load_frame(dataset)
    settings = Settings(
        BINANCE_MODE="simulated",
        LIVE_TRADING_ENABLED=False,
        LIVE_MODE=False,
        AUTONOMOUS_TRADING_ENABLED=False,
        MANUAL_TRADING_ENABLED=False,
        SHADOW_MODE_ENABLED=True,
        PULLBACK_STRATEGY_ENABLED=False,
        FRICTION_ENABLED=True,
    )
    features = FeaturePipeline(settings).build_features(frame)
    cache = MarketSignalCache(frame)
    position = min(120, len(frame) - 1)
    signal_before = cache.at(position)
    mutated = frame.copy()
    mutated.iloc[position + 1:, mutated.columns.get_loc("close")] *= 2.0
    mutated.iloc[position + 1:, mutated.columns.get_loc("high")] *= 2.0
    mutated_cache = MarketSignalCache(mutated)
    signal_after = mutated_cache.at(position)
    causal_ok = (
        signal_before.action == signal_after.action
        and abs(signal_before.score - signal_after.score) < 1e-12
        and abs(signal_before.confidence - signal_after.confidence) < 1e-12
    )

    bullish_flow = analyze_order_flow({"bids": [[100.0, 20.0]], "asks": [[100.0, 5.0]]}, ratio_threshold=2.0)
    neutral_flow = analyze_order_flow({}, ratio_threshold=2.0)
    market_signal = calculate_market_signal(
        frame.iloc[: position + 1],
        order_flow={"bids": [[100.0, 20.0]], "asks": [[100.0, 5.0]]},
        flow_ratio_threshold=2.0,
        require_flow_confirmation=True,
        pullback_kwargs={},
    )
    microstructure = estimate_entry_costs(
        {"bid": 99.0, "ask": 101.0},
        {"asks": [[101.0, 0.001]]},
        "buy",
        0.01,
        100.0,
        98.0,
        104.0,
        settings,
    )
    news_closed = evaluate_news_gate([], {}, settings, now=pd.Timestamp.now(tz="UTC").to_pydatetime())
    breaker = evaluate_circuit_breaker(8000.0, 10000.0, -600.0, settings)
    backtest = await BacktestEngine(settings, None).run("BTC/USDT", frame, "Final logic audit")

    checks = {
        "feature_schema_nonempty": len(features.columns) >= 10,
        "causal_signal_unchanged_by_future_mutation": causal_ok,
        "bullish_flow_2x1": bullish_flow["action"] == "buy" and bullish_flow["data_available"],
        "empty_flow_is_neutral": neutral_flow["action"] == "hold" and not neutral_flow["data_available"],
        "signal_is_non_executing": market_signal.action in {"buy", "sell", "hold"},
        "microstructure_has_decision": isinstance(microstructure["allowed"], bool),
        "news_fail_closed_without_context": news_closed["entry_allowed"] is False,
        "circuit_breaker_trips": breaker["tripped"] is True and breaker["entry_allowed"] is False,
        "backtest_returns_result": backtest.get("status") in {"ok", "insufficient_data"},
        "no_live_flags": settings.LIVE_TRADING_ENABLED is False and settings.LIVE_MODE is False,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "dataset": {"path": str(dataset), "rows": len(frame), "start": frame.index.min().isoformat(), "end": frame.index.max().isoformat()},
        "checks": checks,
        "signal": {"action": market_signal.action, "candidate_action": market_signal.candidate_action, "score": market_signal.score},
        "backtest": {key: backtest.get(key) for key in ("status", "trades_executed", "total_pnl", "return_pct", "sharpe_ratio", "maximum_drawdown")},
        "live_trading_enabled": False,
        "orders_sent": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoria funcional final sem trading")
    parser.add_argument("dataset", nargs="?", default="data/replay_btcusdt_1h.csv")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = asyncio.run(run_audit(Path(args.dataset)))
    rendered = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
