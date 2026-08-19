#!/usr/bin/env python3
"""Calibra parâmetros em uma janela e mede a variante escolhida em teste posterior."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from ai.train_ensemble import train_from_ohlcv
from config.settings import Settings
from core.backtest_engine import BacktestEngine


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"]).set_index("open_time").sort_index()
    return frame[["open", "high", "low", "close", "volume"]]


async def evaluate(frame: pd.DataFrame, model_dir: Path, params: dict) -> dict:
    settings = Settings(
        ENSEMBLE_MODEL_DIR=str(model_dir),
        BACKTEST_USE_ENSEMBLE=True,
        BACKTEST_WARMUP_BARS=500,
        FRICTION_ENABLED=True,
        FRICTION_SLEEP_ENABLED=False,
        FRICTION_COMMISSION_RATE=0.0005,
        FRICTION_TICK_SIZE=0.01,
        FRICTION_SEED=42,
        BACKTEST_FEE_RATE=0.0,
        ECONOMIC_EVENTS_FILE="/tmp/zia-no-economic-events.json",
        BACKTEST_INITIAL_CAPITAL=10_000.0,
        MAX_RISK_PER_TRADE=0.02,
        MAX_EXPOSURE_PER_SYMBOL=0.10,
        **params,
    )
    result = await BacktestEngine(settings, None).run("BTC/USDT", frame, "shadow calibration")
    return {key: result.get(key) for key in ["total_pnl", "return_pct", "sharpe_ratio", "max_drawdown", "trades_executed", "win_rate", "profit_factor", "total_fees", "ensemble_enabled", "ensemble_rejections"]}


def rank(item: dict) -> tuple:
    metrics = item["metrics"]
    trades = int(metrics.get("trades_executed", 0) or 0)
    sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
    drawdown = float(metrics.get("max_drawdown", 0.0) or 0.0)
    eligible = trades >= 10 and drawdown > -0.15
    return (int(eligible), sharpe, float(metrics.get("total_pnl", 0.0) or 0.0), trades)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--output", default="data/shadow_calibration.json")
    args = parser.parse_args()
    source = Path(args.dataset)
    frame = load(source)
    fit_end = int(len(frame) * 0.70)
    calibration_end = int(len(frame) * 0.85)
    fit = frame.iloc[:fit_end]
    calibration = frame.iloc[max(0, fit_end - 500):calibration_end]
    test = frame.iloc[max(0, calibration_end - 500):]
    with tempfile.TemporaryDirectory(prefix="zia-ensemble-fit-") as temp_dir:
        fit_path = Path(temp_dir) / "fit.csv"
        fit.reset_index().rename(columns={"open_time": "open_time"}).to_csv(fit_path, index=False)
        model_dir = Path(temp_dir) / "models"
        training = train_from_ohlcv(fit_path, model_dir=model_dir, horizon=3, buy_threshold=0.001, sell_threshold=-0.001)
        grid = []
        pullback_variants = [
            {"PULLBACK_STRATEGY_ENABLED": False},
            {"PULLBACK_STRATEGY_ENABLED": True, "PULLBACK_TOUCH_TOLERANCE": 0.003, "PULLBACK_EXHAUSTION_VOLUME_RATIO": 0.80, "PULLBACK_TRIGGER_VOLUME_RATIO": 1.30},
            {"PULLBACK_STRATEGY_ENABLED": True, "PULLBACK_TOUCH_TOLERANCE": 0.005, "PULLBACK_EXHAUSTION_VOLUME_RATIO": 0.85, "PULLBACK_TRIGGER_VOLUME_RATIO": 1.20},
            {"PULLBACK_STRATEGY_ENABLED": True, "PULLBACK_TOUCH_TOLERANCE": 0.008, "PULLBACK_EXHAUSTION_VOLUME_RATIO": 0.90, "PULLBACK_TRIGGER_VOLUME_RATIO": 1.10},
            {"PULLBACK_STRATEGY_ENABLED": True, "PULLBACK_TOUCH_TOLERANCE": 0.012, "PULLBACK_EXHAUSTION_VOLUME_RATIO": 0.95, "PULLBACK_TRIGGER_VOLUME_RATIO": 1.05},
        ]
        for pullback_variant in pullback_variants:
            for min_confidence in (0.60, 0.65, 0.70):
                for max_volatility in (0.08, 0.12):
                    params = {
                        **pullback_variant,
                        "MIN_CONFIDENCE_THRESHOLD": min_confidence,
                        "BACKTEST_MAX_VOLATILITY": max_volatility,
                    }
                    metrics = asyncio.run(evaluate(calibration, model_dir, params))
                    grid.append({"params": params, "metrics": metrics})
        chosen = max(grid, key=rank)
        test_metrics = asyncio.run(evaluate(test, model_dir, chosen["params"]))
        result = {
            "dataset": {"rows": len(frame), "first": frame.index[0].isoformat(), "last": frame.index[-1].isoformat()},
            "splits": {"fit_rows": len(fit), "calibration_rows": len(calibration), "test_rows": len(test), "fit_end": fit.index[-1].isoformat(), "calibration_end": calibration.index[-1].isoformat()},
            "training": training,
            "grid": grid,
            "chosen": chosen,
            "test_metrics": test_metrics,
            "selection_rule": "eligible requires >=10 trades and drawdown > -15%; among eligible, maximize calibration Sharpe, then PnL",
            "news_features": "not joined to historical OHLCV because persisted news currently covers the present, not 2020-2024; live news remains deterministic context only",
        }
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"chosen": chosen, "test_metrics": test_metrics, "training_metrics": training.get("validation_metrics")}, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
