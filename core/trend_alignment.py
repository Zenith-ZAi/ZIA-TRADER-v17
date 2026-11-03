"""Veto conservador de entradas desalinhadas com o regime de mercado.

Este componente é apenas um gate adicional: passar nele não autoriza uma ordem.
Modelos, pesos, RiskAI, OrderManager e demais gates permanecem obrigatórios.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MIN_COUNTERTREND_REVERSAL_CONFIDENCE = 0.70


class TrendAlignmentFilter:
    """Bloqueia incerteza, alta volatilidade e contra-tendência sem confirmação."""

    NEUTRAL_REGIMES = {"normal", "low_volatility_sideways", "sideways"}
    BLOCKED_REGIMES = {"unknown", "uncertain", "high_volatility", "news_shock", "liquidity_crisis"}

    def __init__(self, min_reversal_confidence: float = MIN_COUNTERTREND_REVERSAL_CONFIDENCE):
        threshold = float(min_reversal_confidence)
        if not math.isfinite(threshold) or not MIN_COUNTERTREND_REVERSAL_CONFIDENCE <= threshold <= 1.0:
            raise ValueError("min_reversal_confidence deve estar entre 0,70 e 1")
        self.min_reversal_confidence = threshold

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _result(
        passed: bool,
        candidate_action: str,
        regime: str,
        trend_direction: str | None,
        reason: str,
        reversal_override_used: bool = False,
    ) -> dict[str, Any]:
        return {
            "gate": "trend_alignment_v1",
            "passed": passed,
            "status": "passed" if passed else "blocked",
            "candidate_action": candidate_action,
            "regime": regime,
            "trend_direction": trend_direction,
            "reversal_override_used": reversal_override_used,
            "reasons": [reason],
        }

    def evaluate(
        self,
        candidate_action: str,
        regime_info: Mapping[str, Any] | None,
        reversal_signal: Mapping[str, Any] | None,
        order_flow: Mapping[str, Any] | None,
        *,
        microstructure_allowed: bool,
        risk_allowed: bool,
    ) -> dict[str, Any]:
        """Retorna se este gate específico passou; nunca retorna autorização final.

        Uma entrada contra uma tendência forte só passa quando a estratégia de
        reversão existente detectou mudança direcional, o fluxo tem dados
        completos e aponta para a reversão, e os gates de execução/risco passaram.
        """
        action = str(candidate_action or "").strip().lower()
        regime_data = regime_info if isinstance(regime_info, Mapping) else {}
        regime = str(regime_data.get("regime") or "unknown").strip().lower()
        trend_index = self._finite_number(regime_data.get("trend_index"))
        trend_direction = None
        if trend_index is not None and trend_index != 0.0:
            trend_direction = "buy" if trend_index > 0.0 else "sell"

        if action not in {"buy", "sell"}:
            return self._result(False, action or "hold", regime, trend_direction, "sem candidato direcional")
        if risk_allowed is not True:
            return self._result(False, action, regime, trend_direction, "gate de risco não aprovado")
        if microstructure_allowed is not True:
            return self._result(False, action, regime, trend_direction, "microestrutura/execução não aprovada")
        if regime in self.BLOCKED_REGIMES:
            return self._result(False, action, regime, trend_direction, f"regime {regime} bloqueia novas entradas")
        if trend_index is None:
            return self._result(False, action, regime, None, "índice de tendência ausente ou inválido")

        if regime == "strong_trend":
            if trend_direction is None:
                return self._result(False, action, regime, None, "direção da tendência forte indeterminada")
            if action == trend_direction:
                return self._result(True, action, regime, trend_direction, "candidato alinhado à tendência forte")
            if self._confirmed_countertrend_reversal(
                action, trend_direction, reversal_signal, order_flow
            ):
                return self._result(
                    True,
                    action,
                    regime,
                    trend_direction,
                    "reversão contra tendência confirmada por sinal, fluxo, microestrutura e risco",
                    reversal_override_used=True,
                )
            return self._result(False, action, regime, trend_direction, "contra-tendência sem reversão e fluxo confirmados")

        if regime == "reversal_confirmed":
            if self._reversal_matches(action, reversal_signal) and self._flow_matches(action, order_flow):
                return self._result(
                    True, action, regime, trend_direction,
                    "regime de reversão confirmado com fluxo direcional",
                    reversal_override_used=True,
                )
            return self._result(False, action, regime, trend_direction, "regime de reversão sem confirmação suficiente")

        if regime in self.NEUTRAL_REGIMES:
            return self._result(True, action, regime, trend_direction, "regime sem contra-tendência forte")
        return self._result(False, action, regime, trend_direction, f"regime não reconhecido: {regime}")

    def _confirmed_countertrend_reversal(
        self,
        action: str,
        trend_direction: str,
        reversal_signal: Mapping[str, Any] | None,
        order_flow: Mapping[str, Any] | None,
    ) -> bool:
        reversal = reversal_signal if isinstance(reversal_signal, Mapping) else {}
        return bool(
            reversal.get("from") == trend_direction
            and self._reversal_matches(action, reversal)
            and self._flow_matches(action, order_flow)
        )

    def _reversal_matches(self, action: str, reversal_signal: Mapping[str, Any] | None) -> bool:
        reversal = reversal_signal if isinstance(reversal_signal, Mapping) else {}
        confidence = self._finite_number(reversal.get("current_confidence"))
        return bool(
            reversal.get("detected") is True
            and str(reversal.get("to") or "").lower() == action
            and confidence is not None
            and confidence >= self.min_reversal_confidence
        )

    @staticmethod
    def _flow_matches(action: str, order_flow: Mapping[str, Any] | None) -> bool:
        flow = order_flow if isinstance(order_flow, Mapping) else {}
        return bool(flow.get("data_available") is True and str(flow.get("action") or "").lower() == action)
