from types import SimpleNamespace

import numpy as np
import pandas as pd

from ai.whale_detector import WhaleDetector
from core.market_signals import detect_reversal_signal


def test_whale_detector_uses_book_concentration_not_simulated_magnitude():
    detector = WhaleDetector(
        SimpleNamespace(WHALE_ACTIVITY_THRESHOLD=0.05, WHALE_VOLUME_THRESHOLD_MULTIPLIER=3.0),
        None,
    )
    flow = {
        "symbol": "BTC/USDT",
        "buys": [
            {"price": 100.0, "quantity": 1.0},
            {"price": 100.0, "quantity": 40.0},
        ],
        "sells": [
            {"price": 100.0, "quantity": 1.0},
            {"price": 100.0, "quantity": 1.0},
        ],
    }
    result = detector.detect_whale_activity(pd.DataFrame(), flow)
    assert result["detected"] is True
    assert result["large_buys_count"] == 1
    assert result["magnitude"] > 0.0
    assert result["large_buy_notional"] == 4000.0
    assert result["sentiment"] == "bullish"


def test_reversal_requires_history_and_does_not_force_action():
    short = pd.DataFrame({"close": np.linspace(100, 105, 20), "high": np.linspace(101, 106, 20), "low": np.linspace(99, 104, 20), "volume": np.ones(20)})
    result = detect_reversal_signal(short)
    assert result["detected"] is False
    assert result["reason"] == "histórico insuficiente"
