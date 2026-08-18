#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.settings import Settings
from core.market_signals import MarketSignalCache
from core.pullback_strategy import PullbackSignalCache


def main() -> None:
    frame = pd.read_csv(sys.argv[1], parse_dates=["open_time"]).set_index("open_time").sort_index()
    settings = Settings()
    deterministic = MarketSignalCache(frame)
    pullback = PullbackSignalCache(frame, ema_period=settings.PULLBACK_EMA_PERIOD, rsi_period=settings.PULLBACK_RSI_PERIOD, atr_period=settings.PULLBACK_ATR_PERIOD, volume_period=settings.PULLBACK_VOLUME_PERIOD, exhaustion_volume_ratio=settings.PULLBACK_EXHAUSTION_VOLUME_RATIO, trigger_volume_ratio=settings.PULLBACK_TRIGGER_VOLUME_RATIO)
    counts = {"det_buy": 0, "det_sell": 0, "pb_buy": 0, "pb_sell": 0, "aligned_buy": 0, "aligned_sell": 0}
    examples = []
    for index in range(35, len(frame)):
        d = deterministic.at(index, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY)
        p = pullback.at(index)
        counts["det_buy"] += int(d.action == "buy")
        counts["det_sell"] += int(d.action == "sell")
        counts["pb_buy"] += int(p.action == "buy")
        counts["pb_sell"] += int(p.action == "sell")
        counts["aligned_buy"] += int(d.action == "buy" and p.action == "buy")
        counts["aligned_sell"] += int(d.action == "sell" and p.action == "sell")
        if p.valid and len(examples) < 10:
            examples.append({"index": index, "timestamp": frame.index[index].isoformat(), "deterministic": d.action, "pullback": p.action, "confidence": d.confidence, "score": d.score})
    print({"counts": counts, "examples": examples})


if __name__ == "__main__":
    main()
