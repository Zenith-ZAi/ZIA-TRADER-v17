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


class PullbackSignalCache:
    """Pré-calcula indicadores e pivôs uma vez, mantendo confirmação causal por posição."""

    def __init__(self, data: pd.DataFrame, **kwargs: Any):
        self.data = data.copy(deep=True)
        self.kwargs = {
            "ema_period": int(kwargs.get("ema_period", 200)),
            "rsi_period": int(kwargs.get("rsi_period", 14)),
            "atr_period": int(kwargs.get("atr_period", 14)),
            "volume_period": int(kwargs.get("volume_period", 20)),
            "exhaustion_rsi_long": float(kwargs.get("exhaustion_rsi_long", 40.0)),
            "exhaustion_rsi_short": float(kwargs.get("exhaustion_rsi_short", 60.0)),
            "exhaustion_volume_ratio": float(kwargs.get("exhaustion_volume_ratio", 0.80)),
            "trigger_volume_ratio": float(kwargs.get("trigger_volume_ratio", 1.30)),
            "touch_tolerance": float(kwargs.get("touch_tolerance", 0.003)),
            "stop_atr_multiple": float(kwargs.get("stop_atr_multiple", 1.5)),
            "target_atr_multiple": float(kwargs.get("target_atr_multiple", 2.0)),
            "breakeven_atr_trigger": float(kwargs.get("breakeven_atr_trigger", 0.5)),
        }
        self.frame = data[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        self.valid = len(self.frame) == len(data) and len(self.frame) >= max(self.kwargs["ema_period"], 40) + 2
        if not self.valid:
            self._signals: list[PullbackSignal] = [_hold("histórico insuficiente para pullback") for _ in range(len(data))]
            return
        close = self.frame["close"]
        ema = close.ewm(span=self.kwargs["ema_period"], adjust=False, min_periods=self.kwargs["ema_period"]).mean()
        rsi = _rsi(close, self.kwargs["rsi_period"])
        atr = _atr(self.frame, self.kwargs["atr_period"])
        average_volume = self.frame["volume"].rolling(self.kwargs["volume_period"], min_periods=self.kwargs["volume_period"]).mean()
        low_pivots = _last_confirmed_pivots(self.frame["low"], "low")
        high_pivots = _last_confirmed_pivots(self.frame["high"], "high")
        low_pairs = self._confirmed_pairs(low_pivots, len(self.frame))
        high_pairs = self._confirmed_pairs(high_pivots, len(self.frame))
        self._close_series = close
        self._ema_series = ema
        self._rsi_series = rsi
        self._atr_series = atr
        self._average_volume_series = average_volume
        self._open_values = self.frame["open"].tolist()
        self._high_values = self.frame["high"].tolist()
        self._low_values = self.frame["low"].tolist()
        self._close_values = close.tolist()
        self._volume_values = self.frame["volume"].tolist()
        self._ema_fast_state = float(close.ewm(span=self.kwargs["ema_period"], adjust=False).mean().iloc[-1])
        self._bar_count = len(self.frame)
        previous_close = close.shift(1)
        true_range = pd.concat(
            [self.frame["high"] - self.frame["low"], (self.frame["high"] - previous_close).abs(), (self.frame["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        self._true_ranges = true_range.tolist()
        self._low_pivots = list(low_pivots)
        self._high_pivots = list(high_pivots)
        self._low_pairs = list(low_pairs)
        self._high_pairs = list(high_pairs)
        self._signals = []
        for index in range(len(self.frame)):
            self._signals.append(self._signal_at(index, close, ema, rsi, atr, average_volume, low_pairs, high_pairs))

    def extend(self, data: pd.DataFrame) -> bool:
        """Acrescenta somente novas barras quando o cache atual é prefixo idêntico."""
        required = ["open", "high", "low", "close", "volume"]
        if not self.valid or not isinstance(data, pd.DataFrame) or not set(required).issubset(data.columns):
            return False
        if len(data) <= len(self.frame):
            return False
        try:
            normalized = data[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        except (TypeError, ValueError):
            return False
        if len(normalized) != len(data) or len(normalized) <= len(self.frame):
            return False
        old_size = len(self.frame)
        prefix = normalized.iloc[:old_size]
        if not prefix.index.equals(self.frame.index) or not np.array_equal(
            prefix.to_numpy(dtype="float64"), self.frame.to_numpy(dtype="float64")
        ):
            return False
        additions = normalized.iloc[old_size:]
        if not np.isfinite(additions.to_numpy(dtype="float64")).all():
            return False

        p = self.kwargs
        ema_alpha = 2.0 / (float(p["ema_period"]) + 1.0)
        new_ema: list[float] = []
        new_rsi: list[float] = []
        new_atr: list[float] = []
        new_average_volume: list[float] = []

        for timestamp, row in additions.iterrows():
            open_price, high, low, close, volume = (float(row[column]) for column in required)
            previous_close = self._close_values[-1] if self._close_values else None
            self._ema_fast_state = close if self._ema_fast_state is None else ema_alpha * close + (1.0 - ema_alpha) * self._ema_fast_state
            self._bar_count += 1
            ema_value = self._ema_fast_state if self._bar_count >= p["ema_period"] else np.nan

            self._open_values.append(open_price)
            self._high_values.append(high)
            self._low_values.append(low)
            self._close_values.append(close)
            self._volume_values.append(volume)
            true_range = max(
                high - low,
                abs(high - previous_close) if previous_close is not None else np.nan,
                abs(low - previous_close) if previous_close is not None else np.nan,
            )
            self._true_ranges.append(float(true_range))

            deltas = np.diff(self._close_values[-(p["rsi_period"] + 1):])
            if len(deltas) >= p["rsi_period"]:
                average_gain = float(np.maximum(deltas[-p["rsi_period"]:], 0.0).mean())
                average_loss = float(np.maximum(-deltas[-p["rsi_period"]:], 0.0).mean())
                relative_strength = average_gain / average_loss if average_loss else np.nan
                rsi_value = 100.0 - (100.0 / (1.0 + relative_strength)) if np.isfinite(relative_strength) else 50.0
            else:
                rsi_value = 50.0
            atr_values = self._true_ranges[-p["atr_period"]:]
            atr_value = float(np.mean(atr_values)) if len(atr_values) >= p["atr_period"] else np.nan
            volume_values = self._volume_values[-p["volume_period"]:]
            average_value = float(np.mean(volume_values)) if len(volume_values) >= p["volume_period"] else np.nan

            index = len(self._close_values) - 1
            center = index - 2
            if center >= 2:
                pivot_window_low = self._low_values[center - 2:index + 1]
                pivot_window_high = self._high_values[center - 2:index + 1]
                pivot_low = self._low_values[center]
                pivot_high = self._high_values[center]
                if pivot_low <= min(pivot_window_low):
                    self._low_pivots.append((center, pivot_low))
                if pivot_high >= max(pivot_window_high):
                    self._high_pivots.append((center, pivot_high))
            low_pair = tuple(self._low_pivots[-2:]) if len(self._low_pivots) >= 2 else None
            high_pair = tuple(self._high_pivots[-2:]) if len(self._high_pivots) >= 2 else None
            self._low_pairs.append(low_pair)
            self._high_pairs.append(high_pair)
            new_ema.append(float(ema_value) if np.isfinite(ema_value) else np.nan)
            new_rsi.append(float(rsi_value))
            new_atr.append(float(atr_value) if np.isfinite(atr_value) else np.nan)
            new_average_volume.append(float(average_value) if np.isfinite(average_value) else np.nan)

        self.frame = pd.concat([self.frame, additions], axis=0)
        self.data = data.copy(deep=True)
        self._close_series = pd.concat([self._close_series, additions["close"]])
        self._ema_series = pd.concat([self._ema_series, pd.Series(new_ema, index=additions.index)])
        self._rsi_series = pd.concat([self._rsi_series, pd.Series(new_rsi, index=additions.index)])
        self._atr_series = pd.concat([self._atr_series, pd.Series(new_atr, index=additions.index)])
        self._average_volume_series = pd.concat([
            self._average_volume_series,
            pd.Series(new_average_volume, index=additions.index),
        ])
        for index in range(old_size, len(self.frame)):
            self._signals.append(self._signal_at(
                index,
                self._close_series,
                self._ema_series,
                self._rsi_series,
                self._atr_series,
                self._average_volume_series,
                self._low_pairs,
                self._high_pairs,
            ))
        return True

    @staticmethod
    def _confirmed_pairs(pivots: list[tuple[int, float]], size: int) -> list[tuple[tuple[int, float], tuple[int, float]] | None]:
        pairs: list[tuple[tuple[int, float], tuple[int, float]] | None] = [None] * size
        active: list[tuple[int, float]] = []
        cursor = 0
        for index in range(size):
            while cursor < len(pivots) and pivots[cursor][0] + 2 <= index:
                active.append(pivots[cursor])
                cursor += 1
            if len(active) >= 2:
                pairs[index] = (active[-2], active[-1])
        return pairs

    def _signal_at(self, index: int, close: pd.Series, ema: pd.Series, rsi: pd.Series, atr: pd.Series, average_volume: pd.Series, low_pairs: list[tuple[tuple[int, float], tuple[int, float]] | None], high_pairs: list[tuple[tuple[int, float], tuple[int, float]] | None]) -> PullbackSignal:
        p = self.kwargs
        if index < max(p["ema_period"], 40) + 1:
            return _hold("histórico insuficiente para EMA e confirmação do pullback")
        current_price = float(close.iloc[index])
        atr_value = float(atr.iloc[index]) if np.isfinite(atr.iloc[index]) else 0.0
        ema_value = float(ema.iloc[index]) if np.isfinite(ema.iloc[index]) else 0.0
        if current_price <= 0 or atr_value <= 0 or ema_value <= 0:
            return _hold("ATR ou EMA ainda não disponível")
        low_pair = low_pairs[index]
        high_pair = high_pairs[index]
        long_line = _line_at(low_pair[0], low_pair[1], index) if low_pair and low_pair[1][1] > low_pair[0][1] else None
        short_line = _line_at(high_pair[0], high_pair[1], index) if high_pair and high_pair[1][1] < high_pair[0][1] else None
        previous = index - 1
        volume_now = float(self.frame["volume"].iloc[index])
        volume_previous = float(self.frame["volume"].iloc[previous])
        average_now = float(average_volume.iloc[index]) if np.isfinite(average_volume.iloc[index]) else 0.0
        average_previous = float(average_volume.iloc[previous]) if np.isfinite(average_volume.iloc[previous]) else 0.0
        rsi_now = float(rsi.iloc[index])
        rsi_previous = float(rsi.iloc[previous])
        previous_high = float(self.frame["high"].iloc[previous])
        previous_low = float(self.frame["low"].iloc[previous])
        bullish = current_price > ema_value
        bearish = current_price < ema_value
        long_touch = bool(long_line and self.frame["low"].iloc[previous] <= long_line * (1 + p["touch_tolerance"]) and self.frame["close"].iloc[previous] >= long_line)
        short_touch = bool(short_line and self.frame["high"].iloc[previous] >= short_line * (1 - p["touch_tolerance"]) and self.frame["close"].iloc[previous] <= short_line)
        long_exhaustion = bool(long_touch and rsi_previous < p["exhaustion_rsi_long"] and average_previous > 0 and volume_previous < average_previous * p["exhaustion_volume_ratio"])
        short_exhaustion = bool(short_touch and rsi_previous > p["exhaustion_rsi_short"] and average_previous > 0 and volume_previous < average_previous * p["exhaustion_volume_ratio"])
        long_trigger = bool(long_exhaustion and current_price > previous_high and rsi_previous <= 50 < rsi_now and average_now > 0 and volume_now > average_now * p["trigger_volume_ratio"])
        short_trigger = bool(short_exhaustion and current_price < previous_low and rsi_previous >= 50 > rsi_now and average_now > 0 and volume_now > average_now * p["trigger_volume_ratio"])
        if bullish and long_line and long_touch:
            candidate, valid, exhaustion, trigger, trendline = "buy", long_trigger, long_exhaustion, long_trigger, float(long_line)
            stop_loss = current_price - p["stop_atr_multiple"] * atr_value
            take_profit = current_price + p["target_atr_multiple"] * atr_value
            breakeven = current_price + p["breakeven_atr_trigger"] * atr_value
        elif bearish and short_line and short_touch:
            candidate, valid, exhaustion, trigger, trendline = "sell", short_trigger, short_exhaustion, short_trigger, float(short_line)
            stop_loss = current_price + p["stop_atr_multiple"] * atr_value
            take_profit = current_price - p["target_atr_multiple"] * atr_value
            breakeven = current_price - p["breakeven_atr_trigger"] * atr_value
        else:
            return _hold("sem toque confirmado de linha de tendência sob EMA")
        confidence = 0.25 + (0.25 if exhaustion else 0.0) + (0.25 if trigger else 0.0) + (0.25 if (bullish or bearish) else 0.0)
        reasons = [
            "filtro macro confirmado",
            "pivôs de swing projetam linha de tendência dinâmica",
            "toque da linha detectado",
            "exaustão confirmada" if exhaustion else "exaustão não confirmada",
            "rompimento confirmado" if trigger else "rompimento não confirmado",
        ]
        return PullbackSignal(candidate if valid else "hold", candidate, valid, "alta" if bullish else "baixa", True, exhaustion, trigger, float(confidence), current_price, atr_value, trendline, float(stop_loss), float(take_profit), float(breakeven), reasons)

    def at(self, position: int) -> PullbackSignal:
        if position < 0 or position >= len(self._signals):
            return _hold("posição fora do cache pullback")
        return self._signals[position]
