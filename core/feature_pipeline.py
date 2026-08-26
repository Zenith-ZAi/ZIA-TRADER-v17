"""Pipeline de features compartilhado entre live, backtest e treino."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple

import pandas as pd

from ai.feature_pipeline import MODEL_FEATURE_COLUMNS, build_feature_frame, build_supervised_dataset


@dataclass(frozen=True)
class FeaturePipeline:
    """Contrato único; parâmetros futuros podem ser injetados sem duplicar lógica."""

    settings: Any | None = None

    def build_features(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        return build_feature_frame(ohlcv)

    def build_supervised(self, ohlcv: pd.DataFrame, horizon: int = 3, buy_threshold: float = 0.001, sell_threshold: float = -0.001) -> Tuple[pd.DataFrame, pd.Series]:
        return build_supervised_dataset(ohlcv, horizon, buy_threshold, sell_threshold)

    @property
    def schema(self) -> list[str]:
        return list(MODEL_FEATURE_COLUMNS)

    def latest(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        return self.build_features(ohlcv).dropna().tail(1)
