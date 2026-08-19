from types import SimpleNamespace

import pandas as pd

from config.settings import Settings
from core.pattern_memory import PatternMemory, build_pattern_signature
from core.position_policy import evaluate_position_exit


class _DB:
    def __init__(self, records):
        self.records = records

    def get_market_patterns(self, symbol=None, strategy=None, limit=5000):
        return self.records


def _signal(action="buy"):
    return SimpleNamespace(
        action=action,
        confidence=0.9,
        indicators={"rsi": 35.0, "atr_pct": 0.01},
        pullback={"confidence": 1.0, "exhaustion": True, "trigger": True},
    )


def test_pattern_signature_is_causal_and_numeric():
    data = pd.DataFrame(
        {
            "close": [100.0, 101.0, 100.5, 102.0, 103.0, 104.0],
            "volume": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
        }
    )
    signature = build_pattern_signature(data, _signal(), 0.4, 0.3)
    assert signature["direction"] == 1.0
    assert signature["news_sentiment"] == 0.4
    assert all(isinstance(value, float) for value in signature.values())


def test_pattern_memory_requires_profitable_historical_pattern():
    settings = Settings(PATTERN_MEMORY_ENABLED=True, PATTERN_MEMORY_MIN_SAMPLES=2, PATTERN_MEMORY_MIN_OUTCOME_ATR=2.0)
    signature = build_pattern_signature(pd.DataFrame({"close": [100.0] * 6, "volume": [10.0] * 6}), _signal())
    record = SimpleNamespace(
        id=7,
        outcome_atr=2.5,
        sample_size=2,
        signature_json=signature,
    )
    match = PatternMemory(_DB([record]), settings).find_match("BTC/USDT", signature)
    assert match.matched is True
    assert match.pattern_id == 7


def test_position_policy_prioritizes_stop_over_target_in_ohlc_bar():
    decision = evaluate_position_exit(
        {"action": "buy", "entry_price": 100.0, "stop_loss": 98.0, "take_profit": 104.0, "breakeven_trigger": 102.0},
        101.0,
        high=105.0,
        low=97.0,
    )
    assert decision["should_exit"] is True
    assert decision["reason"] == "stop_loss"
    assert decision["exit_action"] == "sell"


def test_position_policy_exits_on_confirmed_reversal():
    decision = evaluate_position_exit(
        {"action": "buy", "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
        103.0,
        reversal_signal={"detected": True, "to": "sell"},
    )
    assert decision["should_exit"] is True
    assert decision["reason"] == "reversal_confirmada"
