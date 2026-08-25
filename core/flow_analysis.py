"""Leitura determinística do desequilíbrio comprador/vendedor."""

from __future__ import annotations

from typing import Any, Iterable


def _level_values(level: Any) -> tuple[float, float]:
    if isinstance(level, dict):
        price = level.get("price", level.get("p", 0.0))
        quantity = level.get("quantity", level.get("qty", level.get("q", 0.0)))
        return float(price or 0.0), float(quantity or 0.0)
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0] or 0.0), float(level[1] or 0.0)
    return 0.0, 0.0


def _notional(levels: Iterable[Any] | None) -> float:
    total = 0.0
    for level in levels or []:
        price, quantity = _level_values(level)
        if price > 0.0 and quantity > 0.0:
            total += price * quantity
    return float(total)


def analyze_order_flow(
    order_book: dict[str, Any] | None,
    ratio_threshold: float = 2.0,
) -> dict[str, Any]:
    """Classifica fluxo comprador/vendedor sem transformar ausência de dados em sinal.

    A interpretação usada é a convenção de microestrutura: predominância de
    compras indica pressão de alta e predominância de vendas indica pressão de
    baixa. O sinal direcional só existe quando um lado alcança a razão mínima;
    caso contrário, o resultado permanece neutro.
    """
    book = order_book or {}
    buy_notional = _notional(book.get("bids"))
    sell_notional = _notional(book.get("asks"))
    total = buy_notional + sell_notional
    threshold = max(float(ratio_threshold), 1.0)
    complete_book = buy_notional > 0.0 and sell_notional > 0.0
    ratio = max(buy_notional / sell_notional, sell_notional / buy_notional) if complete_book else None
    imbalance = (buy_notional - sell_notional) / total if total > 0.0 else 0.0

    if complete_book and buy_notional >= threshold * sell_notional:
        direction = "bullish"
        action = "buy"
        dominant_side = "buyers"
    elif complete_book and sell_notional >= threshold * buy_notional:
        direction = "bearish"
        action = "sell"
        dominant_side = "sellers"
    else:
        direction = "neutral"
        action = "hold"
        dominant_side = "balanced" if total > 0.0 else "unknown"

    return {
        "direction": direction,
        "action": action,
        "dominant_side": dominant_side,
        "buy_notional": float(buy_notional),
        "sell_notional": float(sell_notional),
        "total_notional": float(total),
        "imbalance": float(imbalance),
        "ratio": float(ratio) if ratio is not None else None,
        "ratio_threshold": float(threshold),
        "data_available": bool(complete_book),
        "reason": (
            f"compradores dominam por pelo menos {threshold:.2f}x"
            if direction == "bullish"
            else f"vendedores dominam por pelo menos {threshold:.2f}x"
            if direction == "bearish"
            else "fluxo insuficiente ou sem dominância 2x1"
        ),
    }
