"""Estimativas conservadoras de custo de execução antes da entrada."""

from __future__ import annotations

from typing import Any, Dict


def _best_level(levels: Any) -> tuple[float, float]:
    if not isinstance(levels, list) or not levels:
        return 0.0, 0.0
    level = levels[0]
    if isinstance(level, dict):
        return float(level.get("price", 0.0) or 0.0), float(level.get("quantity", 0.0) or 0.0)
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    return 0.0, 0.0


def estimate_entry_costs(
    market_data: Dict[str, Any] | None,
    order_flow: Dict[str, Any] | None,
    action: str,
    quantity: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    settings: Any,
) -> Dict[str, Any]:
    market = market_data or {}
    flow = order_flow or {}
    bid = float(market.get("bid", 0.0) or 0.0)
    ask = float(market.get("ask", 0.0) or 0.0)
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(entry_price)
    spread_bps = ((ask - bid) / mid * 10000.0) if mid > 0 and ask >= bid else 0.0
    levels = flow.get("asks" if action == "buy" else "bids", [])
    best_price, best_quantity = _best_level(levels)
    default_tick_size = "FOREX_TICK_SIZE" if str(getattr(settings, "MARKET_ADAPTER", "binance")).lower() == "forex" else "FRICTION_TICK_SIZE"
    tick_size = max(float(getattr(settings, default_tick_size, 0.01)), 1e-12)
    configured_slippage_ticks = max(
        float(getattr(settings, "FRICTION_MAX_SLIPPAGE_TICKS", 2.0)),
        0.0,
    )
    if best_price > 0 and quantity > best_quantity > 0:
        depth_shortfall = abs(quantity - best_quantity) / max(best_quantity, 1e-12)
    else:
        depth_shortfall = 0.0
    estimated_slippage_price = tick_size * configured_slippage_ticks * (1.0 + depth_shortfall)
    estimated_slippage_bps = estimated_slippage_price / max(float(entry_price), 1e-12) * 10000.0
    stop_distance = abs(float(entry_price) - float(stop_loss))
    target_distance = abs(float(take_profit) - float(entry_price))
    reward_risk = target_distance / stop_distance if stop_distance > 0 else 0.0
    fee_rate = max(float(getattr(settings, "BACKTEST_FEE_RATE", 0.001)), 0.0)
    round_trip_cost = spread_bps / 10000.0 + estimated_slippage_bps / 10000.0 + (2.0 * fee_rate)
    cost_notional = round_trip_cost * float(entry_price) * float(quantity)
    spread_ok = spread_bps <= float(getattr(settings, "MAX_SPREAD_BPS", 30.0))
    slippage_ok = estimated_slippage_bps <= float(getattr(settings, "MAX_ESTIMATED_SLIPPAGE_BPS", 20.0))
    reward_risk_ok = reward_risk >= float(getattr(settings, "MIN_REWARD_RISK_RATIO", 1.2))
    gate_enabled = bool(getattr(settings, "MICROSTRUCTURE_GATE_ENABLED", True))
    allowed = not gate_enabled or (spread_ok and slippage_ok and reward_risk_ok)
    reasons = []
    if not spread_ok:
        reasons.append("spread acima do limite")
    if not slippage_ok:
        reasons.append("slippage estimado acima do limite")
    if not reward_risk_ok:
        reasons.append("payout/recompensa-risco abaixo do mínimo")
    return {
        "allowed": allowed,
        "gate_enabled": gate_enabled,
        "spread_bps": float(spread_bps),
        "estimated_slippage_bps": float(estimated_slippage_bps),
        "round_trip_cost_rate": float(round_trip_cost),
        "estimated_cost_quote": float(cost_notional),
        "reward_risk_ratio": float(reward_risk),
        "best_price": float(best_price),
        "best_quantity": float(best_quantity),
        "reasons": reasons or ["microestrutura dentro dos limites"],
    }
