"""Treinamento supervisionado controlado: OOS, calibração e rollback."""
from __future__ import annotations

import json
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, balanced_accuracy_score

from ai.ensemble_model import EnsembleModel
from ai.train_ensemble import load_ohlcv
from core.feature_pipeline import FeaturePipeline


LABEL_TO_ACTION = {0: "sell", 1: "hold", 2: "buy"}
ACTION_TO_LABEL = {value: key for key, value in LABEL_TO_ACTION.items()}


def _metrics(y_true: pd.Series, predicted: list[tuple[str, float]], forward_returns: pd.Series) -> Dict[str, Any]:
    labels = [ACTION_TO_LABEL[action] for action, _ in predicted]
    truth = y_true.astype(int).tolist()
    directional = []
    for (action, _), value in zip(predicted, forward_returns.astype(float).tolist()):
        directional.append(float(value) if action == "buy" else -float(value) if action == "sell" else 0.0)
    directional_array = np.asarray(directional, dtype=float)
    sharpe = 0.0
    if directional_array.size > 1 and float(directional_array.std(ddof=1)) > 0:
        sharpe = float(directional_array.mean() / directional_array.std(ddof=1) * math.sqrt(252.0))
    signal_count = sum(action in {"buy", "sell"} for action, _ in predicted)
    return {
        "rows": len(truth),
        "signal_count": signal_count,
        "coverage": float(signal_count / len(truth)) if truth else 0.0,
        "precision_macro": float(precision_score(truth, labels, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(truth, labels, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(truth, labels, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(truth, labels)) if truth else 0.0,
        "sharpe_proxy": sharpe,
        "mean_signal_return": float(directional_array.mean()) if directional_array.size else 0.0,
    }


def _calibration(predicted: list[tuple[str, float]], y_true: pd.Series) -> list[Dict[str, Any]]:
    buckets = {"0.50-0.59": [], "0.60-0.69": [], "0.70-0.79": [], "0.80-0.89": [], "0.90-1.00": []}
    for (action, confidence), truth in zip(predicted, y_true.astype(int).tolist()):
        if confidence < 0.60:
            key = "0.50-0.59"
        elif confidence < 0.70:
            key = "0.60-0.69"
        elif confidence < 0.80:
            key = "0.70-0.79"
        elif confidence < 0.90:
            key = "0.80-0.89"
        else:
            key = "0.90-1.00"
        buckets[key].append(int(action == LABEL_TO_ACTION[truth]))
    return [
        {"bin": key, "count": len(values), "observed_accuracy": float(np.mean(values)) if values else None}
        for key, values in buckets.items()
    ]


def _predict(model: EnsembleModel, features: pd.DataFrame) -> list[tuple[str, float]]:
    return [model.predict(row.to_frame().T) for _, row in features.iterrows()]


def train_oos(
    source: str | Path,
    model_dir: str | Path = "models",
    horizon: int = 3,
    buy_threshold: float = 0.001,
    sell_threshold: float = -0.001,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    min_validation_f1: float = 0.34,
) -> Dict[str, Any]:
    """Treina candidato e só publica se superar o modelo anterior ou o piso inicial."""
    ohlcv = load_ohlcv(source)
    pipeline = FeaturePipeline()
    features, labels = pipeline.build_supervised(ohlcv, horizon, buy_threshold, sell_threshold)
    if len(features) < 180:
        raise ValueError("dataset OOS insuficiente; são necessárias pelo menos 180 amostras")
    if not 0.4 <= train_fraction <= 0.8 or not 0.1 <= validation_fraction <= 0.4:
        raise ValueError("frações de treino/validação fora dos limites seguros")
    train_cut = int(len(features) * train_fraction)
    valid_cut = int(len(features) * (train_fraction + validation_fraction))
    train_end = train_cut - max(1, int(horizon))
    if train_end < 60 or valid_cut <= train_cut or len(features) <= valid_cut:
        raise ValueError("divisão OOS cronológica insuficiente")

    X_train, y_train = features.iloc[:train_end], labels.iloc[:train_end]
    X_valid, y_valid = features.iloc[train_cut:valid_cut], labels.iloc[train_cut:valid_cut]
    X_test, y_test = features.iloc[valid_cut:], labels.iloc[valid_cut:]
    close = pd.to_numeric(ohlcv["close"], errors="coerce")
    future_return = close.shift(-horizon) / close - 1.0
    forward_valid = future_return.reindex(X_valid.index).fillna(0.0)
    forward_test = future_return.reindex(X_test.index).fillna(0.0)

    model_path = Path(model_dir)
    model_path.mkdir(parents=True, exist_ok=True)
    existing_metadata_path = model_path / "ensemble_metadata.json"
    previous_metadata = {}
    if existing_metadata_path.exists():
        try:
            previous_metadata = json.loads(existing_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_metadata = {}

    with tempfile.TemporaryDirectory(prefix="zia-ensemble-") as temp_dir:
        candidate = EnsembleModel(temp_dir)
        candidate_metadata = candidate.train(
            X_train,
            y_train,
            metadata={
                "pipeline": "learning.training_pipeline",
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "source": str(source),
                "horizon": horizon,
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "purge_gap": horizon,
                "train_rows": len(X_train),
                "validation_rows": len(X_valid),
                "test_rows": len(X_test),
                "neural_models": "not trained by this controlled Ensemble pipeline",
            },
        )
        valid_predictions = _predict(candidate, X_valid)
        test_predictions = _predict(candidate, X_test)
        valid_metrics = _metrics(y_valid, valid_predictions, forward_valid)
        test_metrics = _metrics(y_test, test_predictions, forward_test)
        candidate_metadata["validation_metrics"] = valid_metrics
        candidate_metadata["test_metrics"] = test_metrics
        candidate_metadata["calibration"] = _calibration(test_predictions, y_test)
        candidate_metadata["decision"] = "candidate_only"

        previous_f1 = float(((previous_metadata.get("validation_metrics") or {}).get("f1_macro", -1.0)))
        accepted = valid_metrics["f1_macro"] >= float(min_validation_f1) and (
            previous_f1 < 0.0 or valid_metrics["f1_macro"] > previous_f1
        )
        if accepted:
            backup = model_path / f"rollback_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            backup.mkdir(parents=True, exist_ok=True)
            for filename in ("rf_model.joblib", "xgb_model.joblib", "ensemble_metadata.json"):
                current = model_path / filename
                if current.exists():
                    shutil.copy2(current, backup / filename)
            for filename in ("rf_model.joblib", "xgb_model.joblib"):
                shutil.copy2(Path(temp_dir) / filename, model_path / filename)
            (model_path / "ensemble_metadata.json").write_text(json.dumps(candidate_metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            candidate_metadata["decision"] = "accepted"
            candidate_metadata["rollback_backup"] = str(backup)
        return candidate_metadata


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--buy-threshold", type=float, default=0.001)
    parser.add_argument("--sell-threshold", type=float, default=-0.001)
    parser.add_argument("--min-validation-f1", type=float, default=0.34)
    args = parser.parse_args()
    print(json.dumps(train_oos(args.dataset, args.model_dir, args.horizon, args.buy_threshold, args.sell_threshold, min_validation_f1=args.min_validation_f1), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
