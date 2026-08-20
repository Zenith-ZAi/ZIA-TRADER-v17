"""Correlação e alocação long-only para portfólio de estratégias/ativos."""

from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd


class CorrelationManager:
    def __init__(self, low_correlation_threshold: float = 0.30, max_weight: float = 1.0):
        self.low_correlation_threshold = float(low_correlation_threshold)
        self.max_weight = min(1.0, max(0.0, float(max_weight)))

    @staticmethod
    def returns_frame(price_data: Mapping[str, pd.Series | pd.DataFrame]) -> pd.DataFrame:
        frames = {}
        for asset, values in price_data.items():
            series = values["close"] if isinstance(values, pd.DataFrame) and "close" in values else values
            frames[str(asset)] = pd.to_numeric(series, errors="coerce").pct_change()
        return pd.DataFrame(frames).replace([np.inf, -np.inf], np.nan).dropna(how="all")

    def correlation_matrix(self, price_data: Mapping[str, pd.Series | pd.DataFrame]) -> pd.DataFrame:
        returns = self.returns_frame(price_data)
        if returns.empty:
            return pd.DataFrame()
        return returns.corr().fillna(0.0)

    def low_correlation_pairs(self, matrix: pd.DataFrame | Mapping[str, Mapping[str, float]]) -> list[dict[str, Any]]:
        frame = matrix if isinstance(matrix, pd.DataFrame) else pd.DataFrame(matrix)
        pairs = []
        for index, first in enumerate(frame.columns):
            for second in frame.columns[index + 1:]:
                value = float(frame.loc[first, second])
                if abs(value) < self.low_correlation_threshold:
                    pairs.append({"asset_a": first, "asset_b": second, "correlation": value})
        return sorted(pairs, key=lambda item: abs(item["correlation"]))

    def markowitz_weights(self, price_data: Mapping[str, pd.Series | pd.DataFrame], risk_free_rate: float = 0.0) -> Dict[str, float]:
        returns = self.returns_frame(price_data)
        if returns.empty or returns.shape[1] == 0:
            return {}
        returns = returns.dropna(axis=1, how="all").fillna(0.0)
        assets = list(returns.columns)
        mean = returns.mean().to_numpy(dtype=float) - float(risk_free_rate)
        covariance = returns.cov().to_numpy(dtype=float)
        covariance = np.nan_to_num(covariance, nan=0.0) + np.eye(len(assets)) * 1e-8
        try:
            raw = np.linalg.pinv(covariance) @ mean
        except np.linalg.LinAlgError:
            raw = np.ones(len(assets), dtype=float)
        raw = np.maximum(raw, 0.0)
        if float(raw.sum()) <= 0:
            volatility = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
            raw = 1.0 / volatility
        weights = raw / max(float(raw.sum()), 1e-12)
        if self.max_weight < 1.0:
            weights = np.minimum(weights, self.max_weight)
            if weights.sum() > 0:
                weights = weights / weights.sum()
        return {asset: float(weight) for asset, weight in zip(assets, weights)}

    def recommend(self, price_data: Mapping[str, pd.Series | pd.DataFrame], risk_free_rate: float = 0.0) -> Dict[str, Any]:
        returns = self.returns_frame(price_data)
        matrix = self.correlation_matrix(price_data)
        weights = self.markowitz_weights(price_data, risk_free_rate=risk_free_rate)
        portfolio_returns = returns[list(weights)].fillna(0.0).mul(pd.Series(weights)).sum(axis=1) if weights else pd.Series(dtype=float)
        return {
            "assets": list(weights),
            "observations": int(len(returns)),
            "correlation_matrix": matrix.to_dict() if not matrix.empty else {},
            "low_correlation_pairs": self.low_correlation_pairs(matrix),
            "weights": weights,
            "portfolio_return_mean": float(portfolio_returns.mean()) if not portfolio_returns.empty else 0.0,
            "portfolio_return_volatility": float(portfolio_returns.std(ddof=1)) if len(portfolio_returns) > 1 else 0.0,
        }
