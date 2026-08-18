"""Detecção auditável de concentração e desequilíbrio no livro de ordens."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd


class WhaleDetector:
    """Identifica ordens desproporcionalmente grandes no fluxo recebido.

    O detector não afirma que uma ordem pertence a uma baleia. Ele mede apenas
    concentração observável no livro e devolve um sinal de contexto.
    """

    def __init__(self, settings, db_manager):
        self.settings = settings
        self.db_manager = db_manager
        self.account_id = "default_account"
        self.threshold = float(getattr(settings, "WHALE_ACTIVITY_THRESHOLD", 0.05))
        self.volume_threshold_multiplier = float(getattr(settings, "WHALE_VOLUME_THRESHOLD_MULTIPLIER", 5.0))

    @staticmethod
    def _notional(order: Dict[str, Any]) -> float:
        if order.get("notional") is not None:
            return max(0.0, float(order.get("notional", 0.0)))
        amount = max(0.0, float(order.get("amount", order.get("quantity", 0.0))))
        price = float(order.get("price", 0.0))
        return amount * price if price > 0 else amount

    def detect_whale_activity(self, historical_data: pd.DataFrame, current_order_flow: Dict[str, Any]) -> Dict[str, Any]:
        buys = list(current_order_flow.get("buys") or [])
        sells = list(current_order_flow.get("sells") or [])
        buy_notionals = [self._notional(order) for order in buys]
        sell_notionals = [self._notional(order) for order in sells]
        all_notionals = [value for value in buy_notionals + sell_notionals if value > 0]
        total_notional = sum(all_notionals)

        if not all_notionals:
            return {
                "detected": False,
                "magnitude": 0.0,
                "sentiment": "neutral",
                "confidence": 0.0,
                "orderbook_imbalance": 0.0,
                "large_buys_count": 0,
                "large_sells_count": 0,
                "large_buy_notional": 0.0,
                "large_sell_notional": 0.0,
                "reason": "livro sem níveis válidos para medir concentração",
            }

        median_notional = float(pd.Series(all_notionals).median())
        threshold_notional = median_notional * max(self.volume_threshold_multiplier, 1.0)
        large_buys = [value for value in buy_notionals if value >= threshold_notional]
        large_sells = [value for value in sell_notionals if value >= threshold_notional]
        large_buy_notional = sum(large_buys)
        large_sell_notional = sum(large_sells)
        concentration = (large_buy_notional + large_sell_notional) / total_notional if total_notional else 0.0
        imbalance = (sum(buy_notionals) - sum(sell_notionals)) / total_notional if total_notional else 0.0
        detected = bool(large_buys or large_sells) and concentration >= self.threshold

        if imbalance >= 0.10 or large_buy_notional > large_sell_notional:
            sentiment = "bullish"
        elif imbalance <= -0.10 or large_sell_notional > large_buy_notional:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
        confidence = min(1.0, 0.5 * abs(imbalance) + 0.5 * concentration)

        if detected and self.db_manager is not None:
            try:
                self.db_manager.create_system_log(
                    "INFO",
                    f"Concentração de livro detectada para {current_order_flow.get('symbol')}. Sentimento: {sentiment}",
                    "WhaleDetector",
                )
            except Exception:
                pass

        return {
            "detected": detected,
            "magnitude": float(concentration),
            "sentiment": sentiment,
            "confidence": float(confidence),
            "orderbook_imbalance": float(imbalance),
            "large_buys_count": len(large_buys),
            "large_sells_count": len(large_sells),
            "large_buy_notional": float(large_buy_notional),
            "large_sell_notional": float(large_sell_notional),
            "threshold_notional": float(threshold_notional),
        }
