"""Replay causal de aprendizado com OHLCV público e fluxo de trades."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings
from core.flow_analysis import analyze_order_flow
from core.dataset_integrity import sha256_frame, validate_ohlcv
from core.decision_snapshot import build_decision_snapshot
from core.learning_layer import SignalLearningLayer
from core.market_signals import calculate_market_signal
from database_manager import DatabaseManager
from scripts.fetch_binance_ohlcv import fetch


def _flow_from_candle(row: pd.Series) -> dict[str, object]:
    price = max(float(row.get("close", 0.0) or 0.0), 1.0)
    buy_notional = max(float(row.get("taker_buy_quote_volume", 0.0) or 0.0), 0.0)
    total_notional = max(float(row.get("quote_asset_volume", 0.0) or 0.0), 0.0)
    sell_notional = max(total_notional - buy_notional, 0.0)
    return {
        "bids": [[price, buy_notional / price]],
        "asks": [[price, sell_notional / price]],
        "source": "binance_public_klines",
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
    }


def run(dataset: pd.DataFrame, database_url: str, symbol: str, horizon_bars: int, timeframe: str = "1h") -> dict[str, object]:
    frame = dataset.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    integrity = validate_ohlcv(frame, timeframe=timeframe, require_closed=True, reject_gaps=False)
    dataset_sha256 = sha256_frame(frame)
    history = frame.set_index("open_time").sort_index()
    settings = Settings(
        DATABASE_URL=database_url,
        ORDER_FLOW_CONFIRMATION_REQUIRED=True,
        PULLBACK_STRATEGY_ENABLED=False,
        PATTERN_MEMORY_ENABLED=False,
        SHADOW_MODE_ENABLED=True,
        LEARNING_FORWARD_HORIZON_BARS=horizon_bars,
    )
    db = DatabaseManager(database_url)
    db.create_tables()
    action_counts: Counter[str] = Counter()
    flow_counts: Counter[str] = Counter()
    observed = 0
    max_position = max(0, len(frame) - horizon_bars)
    for position in range(35, max_position):
        row = frame.iloc[position]
        current_frame = history.iloc[: position + 1]
        order_flow = _flow_from_candle(row)
        flow = analyze_order_flow(order_flow, settings.ORDER_FLOW_RATIO_THRESHOLD)
        signal = calculate_market_signal(
            current_frame,
            min_confidence=float(settings.MIN_CONFIDENCE_THRESHOLD),
            max_volatility=float(settings.BACKTEST_MAX_VOLATILITY),
            order_flow=order_flow,
            flow_ratio_threshold=float(settings.ORDER_FLOW_RATIO_THRESHOLD),
            require_flow_confirmation=True,
            pullback_kwargs={"ema_period": 50},
        )
        observed_at = row["open_time"].to_pydatetime().replace(tzinfo=None)
        db.create_ai_observation({
            "symbol": symbol,
            "observed_at": observed_at,
            "mode": "historical-replay",
            "action": signal.action,
            "candidate_action": signal.candidate_action,
            "confidence": signal.confidence,
            "market_signal_action": signal.action,
            "market_signal_confidence": signal.confidence,
            "price": float(row["close"]),
            "metadata_json": {
                "before": {
                    "indicators": signal.indicators,
                    "flow": flow,
                    "regime": signal.regime,
                    "reasons": signal.reasons,
                },
                "source": "binance_public_klines",
                "bar_position": position,
            },
        })
        db.create_decision_snapshot(build_decision_snapshot(
            symbol=symbol,
            timeframe=timeframe,
            mode="historical-replay",
            action=signal.action,
            candidate_action=signal.candidate_action,
            confidence=signal.confidence,
            gate_status="allowed" if signal.action in {"buy", "sell"} else "blocked",
            before_context={
                "indicators": signal.indicators,
                "flow": flow,
                "regime": signal.regime,
                "reasons": signal.reasons,
                "bar_position": position,
            },
            observed_at=observed_at,
            dataset_sha256=dataset_sha256,
            feature_context=signal.indicators,
        ))
        observed += 1
        action_counts[signal.action] += 1
        flow_counts[str(flow["direction"])] += 1

    learning = SignalLearningLayer(db, settings)
    labels = learning.label_observations(history, symbol=symbol, horizon_bars=horizon_bars)
    return {
        "symbol": symbol,
        "dataset_rows": int(len(frame)),
        "dataset_start": frame["open_time"].iloc[0].isoformat(),
        "dataset_end": frame["open_time"].iloc[-1].isoformat(),
        "dataset_sha256": dataset_sha256,
        "dataset_integrity": integrity,
        "observations_created": observed,
        "actions": dict(action_counts),
        "flow_directions": dict(flow_counts),
        "learning": {key: value for key, value in labels.items() if key != "labels"},
        "orders_sent": 0,
        "live_trading_enabled": False,
        "note": "Replay causal: before foi calculado na barra corrente e after somente em candles futuros disponíveis.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--horizon-bars", type=int, default=8)
    parser.add_argument("--database-url", default="sqlite:///data/learning_replay.db")
    parser.add_argument("--output", default="data/learning_replay_result.json")
    args = parser.parse_args()
    if args.horizon_bars <= 0:
        raise SystemExit("--horizon-bars precisa ser positivo")
    dataset = fetch(args.symbol, args.interval, args.limit)
    result = run(dataset, args.database_url, args.symbol, args.horizon_bars, args.interval)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
