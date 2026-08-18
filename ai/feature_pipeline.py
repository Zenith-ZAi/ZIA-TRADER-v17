"""Features causais e dataset supervisionado para os modelos do ZIA."""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


MODEL_FEATURE_COLUMNS = [
    "return_1",
    "return_3",
    "range_pct",
    "body_pct",
    "volume_zscore",
    "ema_fast_gap",
    "ema_slow_gap",
    "rsi_norm",
    "macd_norm",
    "atr_pct",
]


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"Coluna OHLCV ausente: {column}")
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().all():
        raise ValueError(f"Coluna OHLCV inválida: {column}")
    return values.replace([np.inf, -np.inf], np.nan)


def build_feature_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calcula dez features normalizadas usando apenas a barra atual e anteriores."""
    if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
        raise ValueError("OHLCV vazio ou inválido")
    required = ["open", "high", "low", "close", "volume"]
    frame = pd.DataFrame({column: _numeric(ohlcv, column) for column in required}, index=ohlcv.index)
    close = frame["close"].where(frame["close"] > 0)
    open_price = frame["open"].where(frame["open"] > 0)
    returns = close.pct_change()
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + (gain / loss.replace(0, np.nan))))).fillna(50.0)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_pct = true_range.rolling(14, min_periods=14).mean() / close
    volume_mean = frame["volume"].rolling(20, min_periods=20).mean()
    volume_std = frame["volume"].rolling(20, min_periods=20).std(ddof=0).replace(0, np.nan)
    volume_zscore = (frame["volume"] - volume_mean) / volume_std
    macd_scale = close * atr_pct.clip(lower=0.001)
    features = pd.DataFrame(
        {
            "return_1": returns,
            "return_3": close.pct_change(3),
            "range_pct": (frame["high"] - frame["low"]) / close,
            "body_pct": (frame["close"] - frame["open"]) / open_price,
            "volume_zscore": volume_zscore,
            "ema_fast_gap": ema_fast / ema_slow - 1.0,
            "ema_slow_gap": close / ema_slow - 1.0,
            "rsi_norm": (rsi - 50.0) / 50.0,
            "macd_norm": (macd - macd_signal) / macd_scale,
            "atr_pct": atr_pct,
        },
        index=ohlcv.index,
    )
    return features[MODEL_FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)


def build_supervised_dataset(
    ohlcv: pd.DataFrame,
    horizon: int = 3,
    buy_threshold: float = 0.001,
    sell_threshold: float = -0.001,
) -> Tuple[pd.DataFrame, pd.Series]:
    """Gera X/y sem look-ahead: o rótulo usa somente o retorno após a barra."""
    if horizon < 1:
        raise ValueError("horizon deve ser positivo")
    if sell_threshold >= buy_threshold:
        raise ValueError("sell_threshold deve ser menor que buy_threshold")
    features = build_feature_frame(ohlcv)
    close = _numeric(ohlcv, "close")
    future_return = close.shift(-horizon) / close - 1.0
    labels = pd.Series(
        np.select([future_return <= sell_threshold, future_return >= buy_threshold], [0, 2], default=1),
        index=ohlcv.index,
        name="label",
        dtype="int64",
    )
    valid = features.notna().all(axis=1) & future_return.notna() & np.isfinite(future_return)
    return features.loc[valid].copy(), labels.loc[valid].copy()
