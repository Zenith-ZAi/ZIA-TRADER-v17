import pytest

from core.trend_alignment import TrendAlignmentFilter


def _evaluate(action, regime, **overrides):
    values = {
        "candidate_action": action,
        "regime_info": {"regime": regime, "trend_index": 0.02 if regime == "strong_trend" else 0.0},
        "reversal_signal": {},
        "order_flow": {"data_available": True, "action": action},
        "microstructure_allowed": True,
        "risk_allowed": True,
    }
    values.update(overrides)
    return TrendAlignmentFilter(min_reversal_confidence=0.70).evaluate(**values)


def test_candidate_aligned_with_strong_trend_passes_only_this_gate():
    result = _evaluate("buy", "strong_trend")
    assert result["passed"] is True
    assert result["trend_direction"] == "buy"
    assert result["reversal_override_used"] is False


def test_countertrend_candidate_without_confirmed_reversal_is_blocked():
    result = _evaluate("sell", "strong_trend")
    assert result["passed"] is False
    assert "contra-tendência" in result["reasons"][0]


def test_countertrend_reversal_requires_signal_flow_execution_and_risk():
    result = _evaluate(
        "sell",
        "strong_trend",
        reversal_signal={"detected": True, "from": "buy", "to": "sell", "current_confidence": 0.8},
        order_flow={"data_available": True, "action": "sell"},
    )
    assert result["passed"] is True
    assert result["reversal_override_used"] is True


def test_countertrend_reversal_is_blocked_without_complete_matching_flow():
    result = _evaluate(
        "sell",
        "strong_trend",
        reversal_signal={"detected": True, "from": "buy", "to": "sell", "current_confidence": 0.9},
        order_flow={"data_available": False, "action": "sell"},
    )
    assert result["passed"] is False


def test_countertrend_reversal_is_blocked_when_confidence_or_execution_gate_fails():
    low_confidence = _evaluate(
        "sell",
        "strong_trend",
        reversal_signal={"detected": True, "from": "buy", "to": "sell", "current_confidence": 0.69},
        order_flow={"data_available": True, "action": "sell"},
    )
    bad_execution = _evaluate(
        "sell",
        "strong_trend",
        reversal_signal={"detected": True, "from": "buy", "to": "sell", "current_confidence": 0.9},
        order_flow={"data_available": True, "action": "sell"},
        microstructure_allowed=False,
    )
    assert low_confidence["passed"] is False
    assert bad_execution["passed"] is False


def test_uncertain_high_volatility_and_unknown_regimes_fail_closed():
    for regime in ("uncertain", "high_volatility", "unknown"):
        assert _evaluate("buy", regime)["passed"] is False


def test_risk_gate_failure_blocks_even_aligned_candidate():
    result = _evaluate("buy", "strong_trend", risk_allowed=False)
    assert result["passed"] is False
    assert result["reasons"] == ["gate de risco não aprovado"]


def test_neutral_regime_does_not_claim_order_authorization():
    result = _evaluate("buy", "normal")
    assert result["passed"] is True
    assert "authorization" not in result


def test_countertrend_confidence_floor_cannot_be_configured_lower():
    with pytest.raises(ValueError, match="0,70"):
        TrendAlignmentFilter(min_reversal_confidence=0.69)


def test_missing_boolean_and_nonfinite_trend_index_fail_closed():
    for trend_index in (None, True, float("nan")):
        result = _evaluate(
            "buy",
            "strong_trend",
            regime_info={"regime": "strong_trend", "trend_index": trend_index},
        )
        assert result["passed"] is False
