"""Agregação fail-closed de votos de modelos; não modifica sinais técnicos."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

ACTIONS = {"buy", "sell", "hold"}
MODEL_NAMES = {"transformer", "lstm", "ensemble"}
MIN_AVAILABLE_WEIGHT = 0.40


def aggregate_model_votes(
    predictions: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    minimum_available_weight: float = MIN_AVAILABLE_WEIGHT,
    minimum_action_confidence: float = 0.0,
) -> dict[str, Any]:
    """Normaliza apenas modelos prontos; faltas/invalidade nunca viram voto neutro.

    Regras explícitas: nenhum modelo ou cobertura insuficiente => HOLD; output
    inválido => HOLD; votos buy/sell simultâneos => HOLD; empate/score zero => HOLD.
    O limite de cobertura é uma barreira de disponibilidade, não um novo sinal.
    """
    if not isinstance(weights, Mapping) or set(weights) != MODEL_NAMES:
        return {"action": "hold", "confidence": 0.0, "status": "invalid_weight_schema", "reason": "weights devem cobrir transformer/lstm/ensemble"}
    try:
        normalized_weights = {name: float(weights[name]) for name in MODEL_NAMES}
        minimum = float(minimum_available_weight)
        minimum_confidence = float(minimum_action_confidence)
    except (TypeError, ValueError, KeyError):
        return {"action": "hold", "confidence": 0.0, "status": "invalid_weights", "reason": "pesos não numéricos"}
    if (
        any(not math.isfinite(value) or value < 0.0 for value in normalized_weights.values())
        or not math.isfinite(minimum)
        or not 0.0 < minimum <= 1.0
        or not math.isfinite(minimum_confidence)
        or not 0.0 <= minimum_confidence <= 1.0
        or abs(sum(normalized_weights.values()) - 1.0) > 1e-6
    ):
        return {"action": "hold", "confidence": 0.0, "status": "invalid_weights", "reason": "pesos devem ser finitos, não negativos e somar 1"}

    if not isinstance(predictions, Sequence) or isinstance(predictions, (str, bytes)):
        return {"action": "hold", "confidence": 0.0, "status": "invalid_prediction_set", "reason": "predictions deve ser uma sequência"}
    by_name: dict[str, Mapping[str, Any]] = {}
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            return {"action": "hold", "confidence": 0.0, "status": "invalid_prediction_set", "reason": "voto não é um objeto"}
        name = str(prediction.get("model") or "")
        if name not in MODEL_NAMES or name in by_name:
            return {"action": "hold", "confidence": 0.0, "status": "invalid_prediction_set", "reason": "modelo desconhecido ou voto duplicado"}
        by_name[name] = prediction

    invalid = [name for name, prediction in by_name.items() if prediction.get("status", "ready") != "ready"]
    if invalid:
        return {
            "action": "hold", "confidence": 0.0, "status": "invalid_model_output",
            "reason": f"modelo(s) inválido(s): {','.join(sorted(invalid))}", "invalid_models": sorted(invalid),
        }

    available_weight = sum(normalized_weights[name] for name in by_name)
    if not by_name:
        return {"action": "hold", "confidence": 0.0, "status": "no_ready_models", "reason": "nenhum modelo ativo/aprovado"}
    if available_weight + 1e-12 < minimum:
        return {
            "action": "hold", "confidence": 0.0, "status": "insufficient_model_coverage",
            "reason": "peso disponível abaixo do mínimo; modelos ausentes não são neutralizados",
            "available_weight": available_weight, "minimum_available_weight": minimum,
            "active_models": sorted(by_name),
        }

    scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    versions: dict[str, str] = {}
    for name, prediction in by_name.items():
        action = str(prediction.get("action") or "").lower()
        try:
            confidence = float(prediction.get("confidence"))
        except (TypeError, ValueError):
            confidence = float("nan")
        version = str(prediction.get("version") or "")
        if action not in ACTIONS or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0 or not version:
            return {
                "action": "hold", "confidence": 0.0, "status": "invalid_model_output",
                "reason": f"output/versão inválida para {name}", "invalid_models": [name],
            }
        weight = normalized_weights[name]
        scores[action] += confidence * weight
        versions[name] = version

    directional = [action for action in ("buy", "sell") if scores[action] > 0.0]
    if len(directional) > 1:
        return {
            "action": "hold", "confidence": 0.0, "status": "model_disagreement",
            "reason": "votos direcionais divergentes; entrada bloqueada", "scores": scores,
            "available_weight": available_weight, "active_models": sorted(by_name), "model_versions": versions,
        }
    best_score = max(scores.values())
    tied_actions = [action for action in ("buy", "sell", "hold") if math.isclose(scores[action], best_score, rel_tol=0.0, abs_tol=1e-12)]
    if len(tied_actions) > 1:
        return {
            "action": "hold", "confidence": 0.0, "status": "model_vote_tie_hold",
            "reason": "empate de pontuação; entrada bloqueada", "scores": scores,
            "available_weight": available_weight, "active_models": sorted(by_name), "model_versions": versions,
        }
    best_action = tied_actions[0]
    if best_score <= 0.0:
        best_action = "hold"
        confidence = 0.0
    else:
        confidence = min(1.0, best_score / available_weight)
    if best_action in {"buy", "sell"} and confidence < minimum_confidence:
        return {
            "action": "hold", "confidence": confidence, "status": "low_confidence_hold",
            "reason": "confiança abaixo do threshold operacional existente",
            "scores": scores, "available_weight": available_weight,
            "minimum_action_confidence": minimum_confidence,
            "active_models": sorted(by_name), "model_versions": versions,
        }
    return {
        "action": best_action,
        "confidence": confidence,
        "status": "ready",
        "reason": "voto ponderado normalizado sobre modelos ativos",
        "scores": scores,
        "available_weight": available_weight,
        "active_models": sorted(by_name),
        "model_versions": versions,
    }
