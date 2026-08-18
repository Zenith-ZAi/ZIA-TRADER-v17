#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from core.market_signals import MarketSignalCache


def main() -> None:
    frame = pd.read_csv(sys.argv[1], parse_dates=["open_time"]).set_index("open_time").sort_index()
    cache = MarketSignalCache(frame)
    settings = Settings()
    counts = {"good": 0, "rejected": 0, "bad_data": 0}
    candidates = 0
    for index in range(35, len(frame)):
        signal = cache.at(index, min_confidence=settings.MIN_CONFIDENCE_THRESHOLD, max_volatility=settings.BACKTEST_MAX_VOLATILITY)
        counts[signal.status] = counts.get(signal.status, 0) + 1
        candidates += int(signal.action in {"buy", "sell"})
    print({"rows": len(frame), "counts": counts, "candidates": candidates})


if __name__ == "__main__":
    main()
