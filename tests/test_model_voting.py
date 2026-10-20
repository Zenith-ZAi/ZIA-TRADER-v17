import pytest

from core.model_voting import aggregate_model_votes

WEIGHTS = {"transformer": 0.3, "lstm": 0.3, "ensemble": 0.4}


def vote(model, action, confidence, version="v1"):
    return {"model": model, "action": action, "confidence": confidence, "version": version}


def test_no_models_means_hold_not_synthetic_neutral_vote():
    result = aggregate_model_votes([], WEIGHTS)
    assert result["action"] == "hold"
    assert result["status"] == "no_ready_models"


def test_single_low_weight_model_cannot_authorize_entry():
    result = aggregate_model_votes([vote("transformer", "buy", 0.99)], WEIGHTS)
    assert result["action"] == "hold"
    assert result["status"] == "insufficient_model_coverage"


def test_available_models_are_normalized_and_versions_recorded():
    result = aggregate_model_votes(
        [vote("transformer", "buy", 0.8, "transformer-17"), vote("lstm", "buy", 0.6, "lstm-5")],
        WEIGHTS,
    )
    assert result["action"] == "buy"
    assert result["confidence"] == pytest.approx(0.7)
    assert result["available_weight"] == 0.6
    assert result["model_versions"] == {"transformer": "transformer-17", "lstm": "lstm-5"}


def test_ensemble_only_uses_its_actual_weight_without_missing_models_as_votes():
    result = aggregate_model_votes([vote("ensemble", "sell", 0.75, "ens-42")], WEIGHTS)
    assert result["action"] == "sell"
    assert result["confidence"] == pytest.approx(0.75)
    assert result["active_models"] == ["ensemble"]


def test_opposing_directional_models_force_hold():
    result = aggregate_model_votes(
        [vote("transformer", "buy", 0.99), vote("ensemble", "sell", 0.55)],
        WEIGHTS,
    )
    assert result["action"] == "hold"
    assert result["status"] == "model_disagreement"


def test_zero_confidence_tie_forces_hold():
    result = aggregate_model_votes([vote("ensemble", "buy", 0.0)], WEIGHTS)
    assert result["action"] == "hold"
    assert result["confidence"] == 0.0


def test_exact_score_tie_and_low_confidence_force_hold():
    tie = aggregate_model_votes(
        [vote("transformer", "buy", 0.5), vote("ensemble", "hold", 0.375)],
        WEIGHTS,
    )
    assert tie["action"] == "hold"
    assert tie["status"] == "model_vote_tie_hold"

    low = aggregate_model_votes(
        [vote("ensemble", "buy", 0.4)],
        WEIGHTS,
        minimum_action_confidence=0.5,
    )
    assert low["action"] == "hold"
    assert low["status"] == "low_confidence_hold"


def test_invalid_output_or_version_forces_hold():
    result = aggregate_model_votes([vote("ensemble", "buy", float("nan"))], WEIGHTS)
    assert result["action"] == "hold"
    assert result["status"] == "invalid_model_output"

    missing_version = aggregate_model_votes([vote("ensemble", "buy", 0.9, "")], WEIGHTS)
    assert missing_version["action"] == "hold"
    assert missing_version["status"] == "invalid_model_output"


def test_invalid_weights_or_duplicate_votes_force_hold():
    invalid_weights = aggregate_model_votes([], {"transformer": 0.4, "lstm": 0.3, "ensemble": 0.4})
    assert invalid_weights["action"] == "hold"
    assert invalid_weights["status"] == "invalid_weights"

    duplicate = aggregate_model_votes([vote("ensemble", "buy", 0.8), vote("ensemble", "buy", 0.8)], WEIGHTS)
    assert duplicate["action"] == "hold"
    assert duplicate["status"] == "invalid_prediction_set"
