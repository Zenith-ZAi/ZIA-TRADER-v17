#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.settings import Settings
from core.pullback_strategy import PullbackSignalCache


def main() -> None:
    frame = pd.read_csv(sys.argv[1], parse_dates=["open_time"]).set_index("open_time").sort_index()
    settings = Settings()
    cache = PullbackSignalCache(
        frame,
        ema_period=settings.PULLBACK_EMA_PERIOD,
        rsi_period=settings.PULLBACK_RSI_PERIOD,
        atr_period=settings.PULLBACK_ATR_PERIOD,
        volume_period=settings.PULLBACK_VOLUME_PERIOD,
        exhaustion_volume_ratio=settings.PULLBACK_EXHAUSTION_VOLUME_RATIO,
        trigger_volume_ratio=settings.PULLBACK_TRIGGER_VOLUME_RATIO,
    )
    counts = {"touch": 0, "exhaustion": 0, "trigger": 0, "valid": 0, "buy": 0, "sell": 0}
    for signal in cache._signals:
        counts["touch"] += int(signal.touch)
        counts["exhaustion"] += int(signal.exhaustion)
        counts["trigger"] += int(signal.trigger)
        counts["valid"] += int(signal.valid)
        counts["buy"] += int(signal.action == "buy")
        counts["sell"] += int(signal.action == "sell")
    print(counts)


if __name__ == "__main__":
    main()
