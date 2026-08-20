"""Agregação causal de sinais em múltiplos timeframes.

O módulo não cria candles futuros: cada frame é analisado separadamente e a
confirmação só ocorre quando o timeframe primário concorda com a quantidade
mínima de frames configurada.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable


DEFAULT_TIMEFRAMES = ("1m", "5m", "1h")


def parse_timeframes(raw: str | Iterable[str] | None, fallback: str = "1h") -> list[str]:
    if isinstance(raw, str):
        values = raw.split(",")
    elif raw is None:
        values = [fallback]
    else:
        values = list(raw)
    result: list[str] = []
    for value in values:
        timeframe = str(value).strip()
        if timeframe and timeframe not in result:
            result.append(timeframe)
    if fallback and fallback not in result:
        result.append(fallback)
    return result or [fallback]


def combine_timeframe_signals(
    signals: Dict[str, Any],
    primary_timeframe: str,
    min_confirmations: int = 2,
) -> Dict[str, Any]:
    """Retorna a decisão conjunta sem permitir que um frame isolado autorize entrada."""
    primary = signals.get(primary_timeframe)
    if primary is None and signals:
        primary_timeframe, primary = next(iter(signals.items()))
    if primary is None:
        return {
            "action": "hold",
            "confidence": 0.0,
            "confirmed": False,
            "primary_timeframe": primary_timeframe,
            "confirmations": 0,
            "reasons": ["nenhum timeframe calculado"],
            "signals": {},
        }

    actions = [str(getattr(signal, "action", "hold")) for signal in signals.values()]
    action = str(getattr(primary, "action", "hold"))
    confirmations = sum(candidate == action for candidate in actions) if action in {"buy", "sell"} else 0
    required = max(1, int(min_confirmations))
    confirmed = bool(action in {"buy", "sell"} and confirmations >= required)
    confidence_values = [
        float(getattr(signal, "confidence", 0.0) or 0.0)
        for signal in signals.values()
        if str(getattr(signal, "action", "hold")) == action
    ]
    confidence = min(confidence_values) if confidence_values else float(getattr(primary, "confidence", 0.0) or 0.0)
    reasons = [
        f"timeframe primário={primary_timeframe}",
        f"confirmações={confirmations}/{len(signals)}",
    ]
    if not confirmed:
        reasons.append("matriz multi-timeframe não confirmou a direção")
    return {
        "action": action if confirmed else "hold",
        "confidence": float(confidence),
        "confirmed": confirmed,
        "primary_timeframe": primary_timeframe,
        "confirmations": confirmations,
        "required_confirmations": required,
        "reasons": reasons,
        "signals": {
            timeframe: {
                "action": str(getattr(signal, "action", "hold")),
                "candidate_action": str(getattr(signal, "candidate_action", "hold")),
                "confidence": float(getattr(signal, "confidence", 0.0) or 0.0),
                "volatility": float(getattr(signal, "volatility", 0.0) or 0.0),
                "status": str(getattr(signal, "status", "unknown")),
            }
            for timeframe, signal in signals.items()
        },
    }
