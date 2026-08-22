"""Kelly fracionário adaptativo ao regime de volatilidade."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np


class AdaptiveKellySizer:
    def __init__(self, fraction: float = 0.25, target_volatility: float = 0.02, max_risk_fraction: float = 0.02, min_risk_fraction: float = 0.0):
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.target_volatility = max(1e-9, float(target_volatility))
        self.max_risk_fraction = max(0.0, float(max_risk_fraction))
        self.min_risk_fraction = max(0.0, min(self.max_risk_fraction, float(min_risk_fraction)))

    @staticmethod
    def _win_probability(returns: np.ndarray) -> float:
        wins = returns[returns > 0.0]
        return float(len(wins) / len(returns)) if len(returns) else 0.0

    def estimate(self, returns: Iterable[float], reward_risk: float = 1.0) -> dict[str, Any]:
        values = np.asarray(list(returns), dtype=float)
        values = values[np.isfinite(values)]
        reward_risk = max(1e-9, float(reward_risk))
        volatility = float(np.std(values, ddof=0)) if values.size else 0.0
        win_probability = self._win_probability(values)
        kelly = win_probability - ((1.0 - win_probability) / reward_risk)
        vol_adjustment = min(1.0, self.target_volatility / max(volatility, 1e-9)) if volatility > 0 else 1.0
        risk_fraction = max(self.min_risk_fraction, min(self.max_risk_fraction, kelly * self.fraction * vol_adjustment))
        return {
            "observations": int(values.size),
            "win_probability": win_probability,
            "volatility": volatility,
            "reward_risk": reward_risk,
            "kelly_fraction": float(kelly),
            "fractional_kelly": float(kelly * self.fraction),
            "volatility_adjustment": float(vol_adjustment),
            "risk_fraction": float(max(0.0, risk_fraction)),
            "status": "ok" if values.size >= 20 else "insufficient_history",
        }

    def position_size(self, account_balance: float, entry_price: float, stop_price: float, returns: Iterable[float], reward_risk: float = 1.0) -> dict[str, Any]:
        estimate = self.estimate(returns, reward_risk=reward_risk)
        balance = max(0.0, float(account_balance))
        entry = float(entry_price)
        stop = float(stop_price)
        stop_distance = abs(entry - stop)
        risk_amount = balance * estimate["risk_fraction"]
        quantity = risk_amount / stop_distance if stop_distance > 0 else 0.0
        return {**estimate, "risk_amount": risk_amount, "quantity": quantity, "entry_price": entry, "stop_price": stop}
