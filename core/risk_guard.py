"""Gates de resiliência para entradas e saídas emergenciais."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_circuit_breaker(
    balance: float,
    initial_capital: float,
    daily_pnl: float,
    settings: Any,
) -> Dict[str, Any]:
    enabled = bool(getattr(settings, "CIRCUIT_BREAKER_ENABLED", True))
    max_drawdown = max(0.0, float(getattr(settings, "CIRCUIT_BREAKER_MAX_DRAWDOWN_PERCENT", 0.15)))
    daily_limit = max(0.0, float(getattr(settings, "DAILY_LOSS_LIMIT_PERCENT", 0.05)))
    balance_value = float(balance or 0.0)
    initial_value = float(initial_capital or 0.0)
    drawdown_pct = ((balance_value - initial_value) / initial_value) if initial_value > 0 else 0.0
    drawdown_tripped = enabled and initial_value > 0 and drawdown_pct <= -max_drawdown
    daily_tripped = enabled and balance_value > 0 and float(daily_pnl or 0.0) <= -(daily_limit * balance_value)
    tripped = bool(drawdown_tripped or daily_tripped)
    reasons = []
    if drawdown_tripped:
        reasons.append("drawdown máximo atingido")
    if daily_tripped:
        reasons.append("limite de perda diária atingido")
    return {
        "enabled": enabled,
        "tripped": tripped,
        "entry_allowed": not tripped,
        "drawdown_pct": float(drawdown_pct),
        "max_drawdown_pct": -max_drawdown,
        "daily_pnl": float(daily_pnl or 0.0),
        "reason": "; ".join(reasons) if reasons else "circuit breaker não acionado",
    }


def evaluate_emergency_exit(
    event_status: Dict[str, Any] | None,
    news_gate: Dict[str, Any] | None,
    market_signal: Any | None,
    settings: Any,
) -> Dict[str, Any]:
    if not bool(getattr(settings, "EMERGENCY_EXIT_ENABLED", False)):
        return {"should_exit": False, "reason": "emergency exit desativado"}
    event_blocked = bool((event_status or {}).get("blocked"))
    news_shock = bool((news_gate or {}).get("news_shock"))
    event_enabled = bool(getattr(settings, "EMERGENCY_EXIT_ON_EVENT", False))
    news_enabled = bool(getattr(settings, "EMERGENCY_EXIT_ON_NEWS_SHOCK", False))
    if event_enabled and event_blocked:
        return {"should_exit": True, "reason": "emergency exit por evento econômico"}
    if news_enabled and news_shock:
        return {"should_exit": True, "reason": "emergency exit por choque de notícias"}
    return {"should_exit": False, "reason": "nenhum gatilho de saída emergencial"}
