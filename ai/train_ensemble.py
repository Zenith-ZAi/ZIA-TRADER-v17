"""Treinamento reproduzível do Ensemble a partir de OHLCV real."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, precision_score, recall_score

from ai.ensemble_model import EnsembleModel
from core.feature_pipeline import FeaturePipeline


def load_ohlcv(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source)
    elif source.suffix.lower() in {".parquet", ".pq"}:
        frame = pd.read_parquet(source)
    else:
        raise ValueError("dataset deve ser CSV ou Parquet")
    timestamp_column = "timestamp" if "timestamp" in frame.columns else "open_time" if "open_time" in frame.columns else None
    if timestamp_column:
        frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True, errors="raise")
        frame = frame.set_index(timestamp_column)

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"dataset precisa conter {sorted(required)}")
    return frame.sort_index()


def train_from_ohlcv(
    source: str | Path,
    model_dir: str | Path = "models",
    horizon: int = 3,
    buy_threshold: float = 0.001,
    sell_threshold: float = -0.001,
) -> Dict[str, Any]:
    ohlcv = load_ohlcv(source)
    pipeline = FeaturePipeline()
    X, y = pipeline.build_supervised(ohlcv, horizon, buy_threshold, sell_threshold)
    if len(X) < 120:
        raise ValueError("dataset supervisionado insuficiente; são necessárias pelo menos 120 amostras")
    split = int(len(X) * 0.80)
    train_end = split - horizon
    if train_end < 60 or len(X) - split < 20:
        raise ValueError("divisão cronológica insuficiente para treino/validação")
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_valid, y_valid = X.iloc[split:], y.iloc[split:]
    model = EnsembleModel(str(model_dir))
    metadata = model.train(
        X_train,
        y_train,
        metadata={
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "horizon": horizon,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "train_start": str(X_train.index.min()),
            "train_end": str(X_train.index.max()),
            "validation_start": str(X_valid.index.min()),
            "validation_end": str(X_valid.index.max()),
        },
    )
    predictions = [model.predict(row.to_frame().T)[0] for _, row in X_valid.iterrows()]
    y_pred = [{"sell": 0, "hold": 1, "buy": 2}[action] for action in predictions]
    metrics = {
        "accuracy": float(accuracy_score(y_valid, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_valid, y_pred)),
        "precision_macro": float(precision_score(y_valid, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_valid, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_valid, y_pred, average="macro", zero_division=0)),
        "validation_rows": int(len(y_valid)),
    }
    metadata["validation_metrics"] = metrics
    with Path(model_dir, "ensemble_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, default=str)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--buy-threshold", type=float, default=0.001)
    parser.add_argument("--sell-threshold", type=float, default=-0.001)
    args = parser.parse_args()
    print(json.dumps(train_from_ohlcv(args.dataset, args.model_dir, args.horizon, args.buy_threshold, args.sell_threshold), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
