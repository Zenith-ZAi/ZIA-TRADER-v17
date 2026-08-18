"""Estratégia causal de pullback em três camadas para o ZIA."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PullbackSignal:
    action: str
    candidate_action: str
    valid: bool
    macro_trend: str
    touch: bool
    exhaustion: bool
    trigger: bool
    confidence: float
    entry_price: float
    atr: float
    trendline: float
    stop_loss: float
    take_profit: float
    breakeven_trigger: float
    reasons: list[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _hold(reason: str) -> PullbackSignal:
    return PullbackSignal("hold", "hold", False, "unknown", False, False, False, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [reason])


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + relative_strength))).fillna(50.0)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def _last_confirmed_pivots(values: pd.Series, kind: str, left: int = 2, right: int = 2) -> list[tuple[int, float]]:
    pivots: list[tuple[int, float]] = []
    end = len(values) - right
    for index in range(left, max(left, end)):
        window = values.iloc[index - left:index + right + 1]
        current = float(values.iloc[index])
        if kind == "low" and current <= float(window.min()):
            pivots.append((index, current))
        if kind == "high" and current >= float(window.max()):
            pivots.append((index, current))
    return pivots


def _line_at(first: tuple[int, float], second: tuple[int, float], index: int) -> float:
    first_index, first_value = first
    second_index, second_value = second
    if second_index == first_index:
        return float(second_value)
    slope = (second_value - first_value) / (second_index - first_index)
    return float(second_value + slope * (index - second_index))


def calculate_pullback_signal(
    data: pd.DataFrame,
    ema_period: int = 200,
    rsi_period: int = 14,
    atr_period: int = 14,
    volume_period: int = 20,
    exhaustion_rsi_long: float = 40.0,
    exhaustion_rsi_short: float = 60.0,
    exhaustion_volume_ratio: float = 0.80,
    trigger_volume_ratio: float = 1.30,
    touch_tolerance: float = 0.003,
    stop_atr_multiple: float = 1.5,
    target_atr_multiple: float = 2.0,
    breakeven_atr_trigger: float = 0.5,
) -> PullbackSignal:
    """Retorna somente sinais observáveis até a última barra do frame."""
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(data, pd.DataFrame) or not required.issubset(data.columns):
        return _hold("OHLCV incompleto para pullback")
    if len(data) < max(ema_period, 40) + 2:
        return _hold(f"histórico insuficiente para EMA{ema_period} e confirmação do pullback")

    frame = data[list(required)].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < max(ema_period, 40) + 2:
        return _hold("OHLCV inválido ou insuficiente após limpeza")
    close = frame["close"]
    ema = close.ewm(span=ema_period, adjust=False, min_periods=ema_period).mean()
    rsi = _rsi(close, rsi_period)
    atr = _atr(frame, atr_period)
    average_volume = frame["volume"].rolling(volume_period, min_periods=volume_period).mean()
    index = len(frame) - 1
    previous = index - 1
    current_price = float(close.iloc[index])
    atr_value = float(atr.iloc[index]) if np.isfinite(atr.iloc[index]) else 0.0
    ema_value = float(ema.iloc[index]) if np.isfinite(ema.iloc[index]) else 0.0
    if current_price <= 0 or atr_value <= 0 or ema_value <= 0:
        return _hold("ATR ou EMA ainda não disponível")

    bullish = current_price > ema_value
    bearish = current_price < ema_value
    macro_trend = "alta" if bullish else "baixa" if bearish else "lateral"
    low_pivots = _last_confirmed_pivots(frame["low"], "low")
    high_pivots = _last_confirmed_pivots(frame["high"], "high")
    long_line: Optional[float] = None
    short_line: Optional[float] = None
    if len(low_pivots) >= 2 and low_pivots[-1][1] > low_pivots[-2][1]:
        long_line = _line_at(low_pivots[-2], low_pivots[-1], index)
    if len(high_pivots) >= 2 and high_pivots[-1][1] < high_pivots[-2][1]:
        short_line = _line_at(high_pivots[-2], high_pivots[-1], index)

    volume_now = float(frame["volume"].iloc[index])
    volume_previous = float(frame["volume"].iloc[previous])
    average_now = float(average_volume.iloc[index]) if np.isfinite(average_volume.iloc[index]) else 0.0
    average_previous = float(average_volume.iloc[previous]) if np.isfinite(average_volume.iloc[previous]) else 0.0
    rsi_now = float(rsi.iloc[index])
    rsi_previous = float(rsi.iloc[previous])
    previous_high = float(frame["high"].iloc[previous])
    previous_low = float(frame["low"].iloc[previous])

    long_touch = bool(long_line and frame["low"].iloc[previous] <= long_line * (1 + touch_tolerance) and frame["close"].iloc[previous] >= long_line)
    short_touch = bool(short_line and frame["high"].iloc[previous] >= short_line * (1 - touch_tolerance) and frame["close"].iloc[previous] <= short_line)
    long_exhaustion = bool(long_touch and rsi_previous < exhaustion_rsi_long and average_previous > 0 and volume_previous < average_previous * exhaustion_volume_ratio)
    short_exhaustion = bool(short_touch and rsi_previous > exhaustion_rsi_short and average_previous > 0 and volume_previous < average_previous * exhaustion_volume_ratio)
    long_trigger = bool(long_exhaustion and current_price > previous_high and rsi_previous <= 50 < rsi_now and average_now > 0 and volume_now > average_now * trigger_volume_ratio)
    short_trigger = bool(short_exhaustion and current_price < previous_low and rsi_previous >= 50 > rsi_now and average_now > 0 and volume_now > average_now * trigger_volume_ratio)

    if bullish and long_line and long_touch:
        candidate = "buy"
        valid = long_trigger
        exhaustion = long_exhaustion
        trigger = long_trigger
        trendline = float(long_line)
        stop_loss = current_price - stop_atr_multiple * atr_value
        take_profit = current_price + target_atr_multiple * atr_value
        breakeven = current_price + breakeven_atr_trigger * atr_value
    elif bearish and short_line and short_touch:
        candidate = "sell"
        valid = short_trigger
        exhaustion = short_exhaustion
        trigger = short_trigger
        trendline = float(short_line)
        stop_loss = current_price + stop_atr_multiple * atr_value
        take_profit = current_price - target_atr_multiple * atr_value
        breakeven = current_price - breakeven_atr_trigger * atr_value
    else:
        return _hold(f"sem toque confirmado de linha de tendência sob EMA{ema_period}")

    confidence = 0.25 + (0.25 if exhaustion else 0.0) + (0.25 if trigger else 0.0) + (0.25 if (bullish or bearish) else 0.0)
    reasons = [
        f"filtro macro: preço {'acima' if bullish else 'abaixo'} da EMA{ema_period}",
        "pivôs de swing projetam linha de tendência dinâmica",
        "toque da linha detectado",
        "exaustão de pullback confirmada por RSI e volume" if exhaustion else "exaustão ainda não confirmada",
        "rompimento confirmado por pavio, RSI e volume" if trigger else "rompimento ainda não confirmado",
    ]
    return PullbackSignal(
        action=candidate if valid else "hold",
        candidate_action=candidate,
        valid=valid,
        macro_trend=macro_trend,
        touch=True,
        exhaustion=exhaustion,
        trigger=trigger,
        confidence=float(confidence),
        entry_price=current_price,
        atr=atr_value,
        trendline=trendline,
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        breakeven_trigger=float(breakeven),
        reasons=reasons,
    )
