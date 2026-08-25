"""Aprendizado supervisionado incremental sobre observações shadow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LearningLabel:
    observation_id: int
    symbol: str
    action: str
    current_price: float
    future_price: float
    forward_return: float
    outcome_label: int
    horizon_bars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "symbol": self.symbol,
            "action": self.action,
            "current_price": self.current_price,
            "future_price": self.future_price,
            "forward_return": self.forward_return,
            "outcome_label": self.outcome_label,
            "horizon_bars": self.horizon_bars,
        }


class SignalLearningLayer:
    """Liga a decisão observável ao resultado futuro e ao treino posterior."""

    def __init__(self, db_manager: Any, settings: Any):
        self.db_manager = db_manager
        self.settings = settings
        self.default_horizon = max(1, int(getattr(settings, "LEARNING_FORWARD_HORIZON_BARS", 8)))

    @staticmethod
    def _close_series(frame: pd.DataFrame) -> pd.Series:
        if not isinstance(frame, pd.DataFrame) or "close" not in frame.columns:
            raise ValueError("dataset precisa conter a coluna close")
        close = pd.to_numeric(frame["close"], errors="coerce").replace([float("inf"), -float("inf")], pd.NA).dropna()
        if close.empty:
            raise ValueError("dataset não contém preços válidos")
        return close

    def label_observation(
        self,
        observation: Any,
        close: pd.Series,
        horizon_bars: int | None = None,
    ) -> LearningLabel | None:
        horizon = max(1, int(horizon_bars or self.default_horizon))
        observed_at = pd.Timestamp(observation.observed_at)
        if observed_at.tzinfo is None:
            observed_at = observed_at.tz_localize("UTC")
        else:
            observed_at = observed_at.tz_convert("UTC")
        index = pd.DatetimeIndex(close.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        position = int(index.searchsorted(observed_at, side="right") - 1)
        future_position = position + horizon
        current_price = float(observation.price or 0.0)
        if position < 0 or future_position >= len(close) or current_price <= 0.0:
            return None
        future_price = float(close.iloc[future_position])
        if future_price <= 0.0:
            return None
        action = str(observation.action or observation.candidate_action or "hold").lower()
        direction = 1.0 if action == "buy" else -1.0 if action == "sell" else 0.0
        forward_return = (future_price / current_price - 1.0) * direction
        outcome_label = int(direction != 0.0 and forward_return > 0.0)
        return LearningLabel(
            observation_id=int(observation.id),
            symbol=str(observation.symbol),
            action=action,
            current_price=current_price,
            future_price=future_price,
            forward_return=float(forward_return),
            outcome_label=outcome_label,
            horizon_bars=horizon,
        )

    def label_observations(
        self,
        frame: pd.DataFrame,
        symbol: str | None = None,
        horizon_bars: int | None = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        close = self._close_series(frame)
        observations = self.db_manager.get_unlabeled_ai_observations(symbol=symbol, limit=limit)
        labeled = 0
        skipped = 0
        labels: list[dict[str, Any]] = []
        for observation in observations:
            label = self.label_observation(observation, close, horizon_bars)
            if label is None:
                skipped += 1
                continue
            self.db_manager.update_ai_observation_outcome(
                label.observation_id,
                label.forward_return,
                label.outcome_label,
                after_context={
                    "after": {
                        "future_price": label.future_price,
                        "forward_return": label.forward_return,
                        "outcome_label": label.outcome_label,
                        "horizon_bars": label.horizon_bars,
                    }
                },
            )
            labeled += 1
            labels.append(label.to_dict())
        directional = [item for item in labels if item["action"] in {"buy", "sell"}]
        wins = sum(item["outcome_label"] for item in directional)
        directional_count = len(directional)
        return {
            "symbol": symbol,
            "observations_seen": len(observations),
            "observations_labeled": labeled,
            "observations_skipped": skipped,
            "directional_observations": directional_count,
            "neutral_observations": labeled - directional_count,
            "wins": wins,
            "losses": directional_count - wins,
            "win_rate": wins / directional_count if directional_count else 0.0,
            "horizon_bars": max(1, int(horizon_bars or self.default_horizon)),
            "labels": labels,
            "orders_sent": 0,
        }
