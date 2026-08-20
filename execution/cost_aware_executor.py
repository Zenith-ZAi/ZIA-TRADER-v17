"""Seleção de execução baseada em spread, profundidade e impacto estimado."""

from __future__ import annotations

from typing import Any, Dict, Iterable


class CostAwareExecutor:
    def __init__(self, max_spread_bps: float = 30.0, max_slippage_bps: float = 20.0, max_book_impact: float = 0.10):
        self.max_spread_bps = max(0.0, float(max_spread_bps))
        self.max_slippage_bps = max(0.0, float(max_slippage_bps))
        self.max_book_impact = min(1.0, max(0.0, float(max_book_impact)))

    @staticmethod
    def _levels(snapshot: Dict[str, Any], action: str) -> list:
        if action == "buy":
            return snapshot.get("asks", snapshot.get("sells", [])) or []
        return snapshot.get("bids", snapshot.get("buys", [])) or []

    def estimate(self, snapshot: Dict[str, Any], action: str, quantity: float) -> Dict[str, Any]:
        bid = float(snapshot.get("bid", 0.0) or 0.0)
        ask = float(snapshot.get("ask", 0.0) or 0.0)
        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        spread_bps = ((ask - bid) / mid * 10000.0) if mid > 0 and ask >= bid else float("inf")
        levels = self._levels(snapshot, action)
        first = levels[0] if levels else {}
        best_price = float(first.get("price", 0.0) if isinstance(first, dict) else first[0]) if first else 0.0
        best_quantity = float(first.get("quantity", 0.0) if isinstance(first, dict) else first[1]) if first else 0.0
        requested = max(0.0, float(quantity))
        depth_ratio = requested / max(best_quantity, 1e-12) if best_quantity > 0 else float("inf")
        slippage_bps = max(0.0, depth_ratio - 1.0) * 10.0
        impact_bps = slippage_bps + spread_bps / 2.0
        depth_available = bool(levels)
        depth_ok = (not depth_available) or depth_ratio <= (1.0 + self.max_book_impact)
        allowed = spread_bps <= self.max_spread_bps and slippage_bps <= self.max_slippage_bps and depth_ok
        return {
            "allowed": bool(allowed),
            "spread_bps": float(spread_bps),
            "slippage_bps": float(slippage_bps),
            "impact_bps": float(impact_bps),
            "best_price": float(best_price),
            "best_quantity": float(best_quantity),
            "depth_available": depth_available,
            "requested_quantity": requested,
            "max_quantity": float(best_quantity * (1.0 + self.max_book_impact)) if best_quantity > 0 else 0.0,
            "reason": "custo dentro dos limites" if allowed else "spread, slippage ou impacto acima do limite",
        }

    def adjust_quantity(self, snapshot: Dict[str, Any], action: str, quantity: float) -> Dict[str, Any]:
        estimate = self.estimate(snapshot, action, quantity)
        adjusted = min(max(0.0, float(quantity)), estimate["max_quantity"]) if estimate["max_quantity"] > 0 else 0.0
        estimate["adjusted_quantity"] = float(adjusted)
        estimate["reduced"] = adjusted < float(quantity)
        return estimate

    def choose_execution_window(self, observations: Iterable[Dict[str, Any]], action: str, quantity: float) -> Dict[str, Any]:
        candidates = []
        for observation in observations:
            estimate = self.estimate(observation.get("snapshot", observation), action, quantity)
            candidates.append({"timestamp": observation.get("timestamp"), "estimate": estimate})
        allowed = [candidate for candidate in candidates if candidate["estimate"]["allowed"]]
        selected = min(allowed or candidates, key=lambda item: item["estimate"].get("impact_bps", float("inf"))) if candidates else None
        return {
            "selected": selected,
            "candidates": candidates,
            "status": "selected" if selected else "no_observations",
        }
