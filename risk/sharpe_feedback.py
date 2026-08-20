"""Feedback leve e determinístico de Sharpe para o agente shadow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk.sharpe_analyzer import SharpeAnalyzer


@dataclass(frozen=True)
class SharpeReward:
    reward: float
    sharpe_before: float
    sharpe_after: float
    delta: float
    should_reoptimize: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward": self.reward,
            "sharpe_before": self.sharpe_before,
            "sharpe_after": self.sharpe_after,
            "delta": self.delta,
            "should_reoptimize": self.should_reoptimize,
        }


class SharpeFeedback:
    def __init__(self, analyzer: SharpeAnalyzer | None = None, reoptimize_every: int = 50):
        self.analyzer = analyzer or SharpeAnalyzer()
        self.reoptimize_every = max(1, int(reoptimize_every))
        self.returns: list[float] = []
        self.rewards: list[SharpeReward] = []

    def record(self, trade_return: float) -> SharpeReward:
        before_metrics = self.analyzer.analyze(self.returns)
        self.returns.append(float(trade_return))
        after_metrics = self.analyzer.analyze(self.returns)
        sharpe_before = float(before_metrics["sharpe_ratio"])
        sharpe_after = float(after_metrics["sharpe_ratio"])
        delta = sharpe_after - sharpe_before
        reward = delta if delta >= 0 else delta * 1.5
        result = SharpeReward(
            reward=float(reward),
            sharpe_before=sharpe_before,
            sharpe_after=sharpe_after,
            delta=float(delta),
            should_reoptimize=len(self.returns) % self.reoptimize_every == 0,
        )
        self.rewards.append(result)
        return result

    def snapshot(self) -> dict[str, Any]:
        metrics = self.analyzer.analyze(self.returns)
        return {
            "trades": len(self.returns),
            "returns": list(self.returns),
            "metrics": metrics,
            "latest_reward": self.rewards[-1].to_dict() if self.rewards else None,
            "reoptimization_due": bool(self.rewards and self.rewards[-1].should_reoptimize),
        }
