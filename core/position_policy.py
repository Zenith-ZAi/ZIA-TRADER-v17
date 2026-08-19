from __future__ import annotations

from typing import Any, Dict


def evaluate_position_exit(
    position: Dict[str, Any] | None,
    current_price: float,
    high: float | None = None,
    low: float | None = None,
    market_signal: Any | None = None,
    reversal_signal: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Avalia uma saída sem criar ou enviar uma ordem.

    Stops têm precedência quando stop e alvo aparecem na mesma barra, uma
    escolha conservadora para OHLCV sem sequência intrabar observável.
    """
    if not position:
        return {"should_exit": False, "reason": "sem posição", "exit_action": None, "price": float(current_price)}
    action = str(position.get("action") or "").lower()
    if action not in {"buy", "sell"}:
        return {"should_exit": False, "reason": "direção de posição inválida", "exit_action": None, "price": float(current_price)}
    price = float(current_price)
    high_value = float(high if high is not None else price)
    low_value = float(low if low is not None else price)
    stop = float(position.get("stop_loss") or 0.0)
    target = float(position.get("take_profit") or 0.0)
    entry = float(position.get("entry_price") or 0.0)
    breakeven = float(position.get("breakeven_trigger") or 0.0)
    effective_stop = stop
    if action == "buy" and breakeven > 0 and price >= breakeven:
        effective_stop = max(stop, entry)
    elif action == "sell" and breakeven > 0 and price <= breakeven:
        effective_stop = min(stop, entry) if stop > 0 else entry

    stop_hit = (low_value <= effective_stop) if action == "buy" and effective_stop > 0 else (high_value >= effective_stop) if action == "sell" and effective_stop > 0 else False
    target_hit = (high_value >= target) if action == "buy" and target > 0 else (low_value <= target) if action == "sell" and target > 0 else False
    exit_action = "sell" if action == "buy" else "buy"
    if stop_hit:
        return {"should_exit": True, "reason": "stop_loss", "exit_action": exit_action, "price": float(effective_stop)}
    if target_hit:
        return {"should_exit": True, "reason": "take_profit", "exit_action": exit_action, "price": float(target)}

    reversal = reversal_signal or {}
    opposite = (action == "buy" and reversal.get("to") == "sell") or (action == "sell" and reversal.get("to") == "buy")
    if reversal.get("detected") and opposite:
        return {"should_exit": True, "reason": "reversal_confirmada", "exit_action": exit_action, "price": price}

    signal_action = str(getattr(market_signal, "action", "hold"))
    signal_confidence = float(getattr(market_signal, "confidence", 0.0) or 0.0)
    if signal_confidence >= 0.70 and signal_action == exit_action:
        return {"should_exit": True, "reason": "sinal_contrário_confirmado", "exit_action": exit_action, "price": price}
    return {"should_exit": False, "reason": "posição mantida", "exit_action": None, "price": price}
