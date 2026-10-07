"""Pipeline de features compartilhado entre live, backtest e treino."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Tuple

import numpy as np
import pandas as pd

from ai.feature_pipeline import MODEL_FEATURE_COLUMNS, build_feature_frame, build_supervised_dataset


class FeatureFrameCache:
    """Cache OHLCV com extensão incremental para frames append-only.

    Frames corrigidos, reordenados ou com janela deslizante são recalculados pela
    função canônica. A fórmula das features continua sendo ``build_feature_frame``;
    a via incremental é usada apenas quando a entrada é finita e sua versão anterior
    permanece como prefixo byte-a-byte equivalente em índice e valores.
    """

    _OHLCV = ("open", "high", "low", "close", "volume")

    def __init__(self) -> None:
        self._signature: tuple[Any, ...] | None = None
        self._features: pd.DataFrame | None = None
        self._raw: pd.DataFrame | None = None
        self._reset_incremental_state()

    def _reset_incremental_state(self) -> None:
        self._incremental_ready = False
        self._opens: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._true_ranges: list[float] = []
        self._ema_fast_state: float | None = None
        self._ema_slow_state: float | None = None
        self._macd_signal_state: float | None = None
        self._bar_count = 0
        self._macd_count = 0

    @staticmethod
    def signature(ohlcv: pd.DataFrame) -> tuple[Any, ...]:
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
            return (0, None, None)
        columns = [column for column in FeatureFrameCache._OHLCV if column in ohlcv.columns]
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(ohlcv[columns], index=True).to_numpy(dtype="uint64").tobytes()
        ).hexdigest()
        return (len(ohlcv), str(ohlcv.index[-1]), digest)

    @classmethod
    def _normalized_raw(cls, ohlcv: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                column: pd.to_numeric(ohlcv[column], errors="coerce").astype("float64")
                for column in cls._OHLCV
            },
            index=ohlcv.index,
        )

    @staticmethod
    def _eligible(raw: pd.DataFrame) -> bool:
        if raw.empty or not np.isfinite(raw.to_numpy(dtype="float64")).all():
            return False
        return bool((raw["open"] > 0).all() and (raw["close"] > 0).all())

    def _can_extend(self, raw: pd.DataFrame) -> bool:
        if not self._incremental_ready or self._raw is None or len(raw) <= len(self._raw):
            return False
        old = self._raw
        if not raw.index[:len(old)].equals(old.index):
            return False
        return bool(np.array_equal(raw.iloc[:len(old)].to_numpy(), old.to_numpy()))

    @staticmethod
    def _ema_step(previous: float | None, value: float, span: int) -> float:
        alpha = 2.0 / (float(span) + 1.0)
        return float(value) if previous is None else float(alpha * value + (1.0 - alpha) * previous)

    def _initialize_incremental_state(self, raw: pd.DataFrame) -> None:
        self._reset_incremental_state()
        if not self._eligible(raw):
            return
        self._opens = raw["open"].tolist()
        self._highs = raw["high"].tolist()
        self._lows = raw["low"].tolist()
        self._closes = raw["close"].tolist()
        self._volumes = raw["volume"].tolist()
        close = raw["close"]
        fast = close.ewm(span=12, adjust=False).mean()
        slow = close.ewm(span=26, adjust=False).mean()
        fast_visible = close.ewm(span=12, adjust=False, min_periods=12).mean()
        slow_visible = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd = fast_visible - slow_visible
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        previous_close = close.shift(1)
        true_range = pd.concat(
            [raw["high"] - raw["low"], (raw["high"] - previous_close).abs(), (raw["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        self._true_ranges = true_range.tolist()
        self._ema_fast_state = float(fast.iloc[-1])
        self._ema_slow_state = float(slow.iloc[-1])
        self._macd_signal_state = float(macd_signal.iloc[-1]) if macd_signal.notna().any() else None
        self._bar_count = len(raw)
        self._macd_count = int(macd.notna().sum())
        self._incremental_ready = True

    def _append_feature(self, row: pd.Series) -> dict[str, float]:
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = float(row["volume"])
        previous_close = self._closes[-1] if self._closes else None

        self._ema_fast_state = self._ema_step(self._ema_fast_state, close, 12)
        self._ema_slow_state = self._ema_step(self._ema_slow_state, close, 26)
        self._bar_count += 1
        ema_fast = self._ema_fast_state if self._bar_count >= 12 else np.nan
        ema_slow = self._ema_slow_state if self._bar_count >= 26 else np.nan
        macd = ema_fast - ema_slow if np.isfinite(ema_fast) and np.isfinite(ema_slow) else np.nan
        if np.isfinite(macd):
            self._macd_signal_state = self._ema_step(self._macd_signal_state, float(macd), 9)
            self._macd_count += 1
        macd_signal = self._macd_signal_state if self._macd_count >= 9 else np.nan

        true_range = max(
            high - low,
            abs(high - previous_close) if previous_close is not None else np.nan,
            abs(low - previous_close) if previous_close is not None else np.nan,
        )
        self._opens.append(open_price)
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        self._volumes.append(volume)
        self._true_ranges.append(float(true_range))

        close_values = self._closes
        returns = close / previous_close - 1.0 if previous_close is not None else np.nan
        return_3 = close / close_values[-4] - 1.0 if len(close_values) >= 4 else np.nan
        deltas = np.diff(close_values[-15:])
        if len(deltas) >= 14:
            average_gain = float(np.maximum(deltas[-14:], 0.0).mean())
            average_loss = float(np.maximum(-deltas[-14:], 0.0).mean())
            relative_strength = average_gain / average_loss if average_loss else np.nan
            rsi = 100.0 - (100.0 / (1.0 + relative_strength)) if np.isfinite(relative_strength) else 50.0
        else:
            rsi = 50.0

        atr_values = self._true_ranges[-14:]
        atr = float(np.mean(atr_values)) if len(atr_values) >= 14 else np.nan
        atr_pct = atr / close if np.isfinite(atr) else np.nan
        volume_values = np.asarray(self._volumes[-20:], dtype="float64")
        if len(volume_values) >= 20:
            volume_mean = float(volume_values.mean())
            volume_std = float(volume_values.std(ddof=0))
            volume_zscore = (volume - volume_mean) / volume_std if volume_std else np.nan
        else:
            volume_zscore = np.nan

        macd_scale = close * max(atr_pct, 0.001) if np.isfinite(atr_pct) else np.nan
        macd_norm = (macd - macd_signal) / macd_scale if np.isfinite(macd) and np.isfinite(macd_signal) and macd_scale else np.nan
        return {
            "return_1": returns,
            "return_3": return_3,
            "range_pct": (high - low) / close,
            "body_pct": (close - open_price) / open_price,
            "volume_zscore": volume_zscore,
            "ema_fast_gap": ema_fast / ema_slow - 1.0 if np.isfinite(ema_fast) and np.isfinite(ema_slow) else np.nan,
            "ema_slow_gap": close / ema_slow - 1.0 if np.isfinite(ema_slow) else np.nan,
            "rsi_norm": (rsi - 50.0) / 50.0,
            "macd_norm": macd_norm,
            "atr_pct": atr_pct,
        }

    def get(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        signature = self.signature(ohlcv)
        if self._signature == signature and self._features is not None:
            return self._features
        required = set(self._OHLCV)
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty or not required.issubset(ohlcv.columns):
            return build_feature_frame(ohlcv)

        raw = self._normalized_raw(ohlcv)
        if self._can_extend(raw) and self._eligible(raw.iloc[len(self._raw):]):
            old_length = len(self._raw)
            additions: list[dict[str, float]] = []
            for _, row in raw.iloc[old_length:].iterrows():
                additions.append(self._append_feature(row))
            added_features = pd.DataFrame(additions, index=raw.index[old_length:], columns=MODEL_FEATURE_COLUMNS)
            self._raw = raw
            self._features = pd.concat([self._features, added_features], axis=0)
            self._signature = signature
            return self._features

        self._features = build_feature_frame(ohlcv)
        self._raw = raw
        self._signature = signature
        self._initialize_incremental_state(raw)
        return self._features

    def clear(self) -> None:
        self._signature = None
        self._features = None
        self._raw = None
        self._reset_incremental_state()


@dataclass(frozen=True)
class FeaturePipeline:
    """Contrato único; parâmetros futuros podem ser injetados sem duplicar lógica."""

    settings: Any | None = None
    cache: FeatureFrameCache = field(default_factory=FeatureFrameCache, compare=False, repr=False)

    def build_features(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        return self.cache.get(ohlcv)

    def build_supervised(self, ohlcv: pd.DataFrame, horizon: int = 3, buy_threshold: float = 0.001, sell_threshold: float = -0.001) -> Tuple[pd.DataFrame, pd.Series]:
        return build_supervised_dataset(ohlcv, horizon, buy_threshold, sell_threshold)

    @property
    def schema(self) -> list[str]:
        return list(MODEL_FEATURE_COLUMNS)

    def latest(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        return self.build_features(ohlcv).dropna().tail(1)
