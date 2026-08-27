"""Pipeline de features compartilhado entre live, backtest e treino."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple

import hashlib

import pandas as pd

from ai.feature_pipeline import MODEL_FEATURE_COLUMNS, build_feature_frame, build_supervised_dataset


class FeatureFrameCache:
    """Cache local de features; invalida se qualquer entrada OHLCV mudar."""

    def __init__(self) -> None:
        self._signature: tuple[Any, ...] | None = None
        self._features: pd.DataFrame | None = None

    @staticmethod
    def signature(ohlcv: pd.DataFrame) -> tuple[Any, ...]:
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
            return (0, None, None)
        columns = [column for column in ("open", "high", "low", "close", "volume") if column in ohlcv.columns]
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(ohlcv[columns], index=True).to_numpy(dtype="uint64").tobytes()
        ).hexdigest()
        return (len(ohlcv), str(ohlcv.index[-1]), digest)

    def get(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        signature = self.signature(ohlcv)
        if self._signature == signature and self._features is not None:
            return self._features
        self._features = build_feature_frame(ohlcv)
        self._signature = signature
        return self._features

    def clear(self) -> None:
        self._signature = None
        self._features = None


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
