"""Treinamento controlado: reprodutibilidade, walk-forward OOS, calibração e registry."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score

from ai.ensemble_model import EnsembleModel
from ai.train_ensemble import load_ohlcv
from core.dataset_integrity import sha256_file, sha256_frame, validate_ohlcv
from core.feature_pipeline import FeaturePipeline
from learning.model_drift import build_drift_reference
from learning.model_registry import ModelRegistryStore, artifact_sha256
from learning.model_validation import evaluate_walk_forward, probability_metrics, write_validation_report


LABEL_TO_ACTION = {0: "sell", 1: "hold", 2: "buy"}
ACTION_TO_LABEL = {value: key for key, value in LABEL_TO_ACTION.items()}
_ARTIFACT_FILES = ("rf_model.joblib", "xgb_model.joblib", "ensemble_metadata.json")


def _metrics(y_true: pd.Series, predicted: list[tuple[str, float]], forward_returns: pd.Series) -> Dict[str, Any]:
    labels = [ACTION_TO_LABEL[action] for action, _ in predicted]
    truth = y_true.astype(int).tolist()
    truth_array = np.asarray(truth, dtype=int)
    predicted_array = np.asarray(labels, dtype=int)
    directional = []
    for (action, _), value in zip(predicted, forward_returns.astype(float).tolist()):
        directional.append(float(value) if action == "buy" else -float(value) if action == "sell" else 0.0)
    directional_array = np.asarray(directional, dtype=float)
    sharpe = 0.0
    if directional_array.size > 1 and float(directional_array.std(ddof=1)) > 0:
        sharpe = float(directional_array.mean() / directional_array.std(ddof=1) * np.sqrt(252.0))
    signal_count = sum(action in {"buy", "sell"} for action, _ in predicted)
    return {
        "rows": len(truth),
        "signal_count": signal_count,
        "coverage": float(signal_count / len(truth)) if truth else 0.0,
        "accuracy": float(np.mean(np.asarray(truth) == np.asarray(labels))) if truth else 0.0,
        "precision_macro": float(precision_score(truth, labels, labels=[0, 1, 2], average="macro", zero_division=0)),
        "recall_macro": float(recall_score(truth, labels, labels=[0, 1, 2], average="macro", zero_division=0)),
        "f1_macro": float(f1_score(truth, labels, labels=[0, 1, 2], average="macro", zero_division=0)),
        "balanced_accuracy": float(np.mean([
            np.mean(predicted_array[truth_array == label] == label)
            for label in np.unique(truth_array)
        ])) if truth else 0.0,
        "sharpe_proxy": sharpe,
        "mean_signal_return": float(directional_array.mean()) if directional_array.size else 0.0,
    }


def _predict(model: EnsembleModel, features: pd.DataFrame) -> list[tuple[str, float]]:
    return [model.predict(row.to_frame().T) for _, row in features.iterrows()]


def _default_registry_store() -> tuple[ModelRegistryStore, Any]:
    """Inicializa o registry no DB configurado e retorna seu manager proprietário."""
    from config.settings import settings
    from database_manager import DatabaseManager

    db_manager = DatabaseManager(settings.DATABASE_URL)
    db_manager.create_tables()
    return ModelRegistryStore(db_manager), db_manager


def _restore_previous_files(model_dir: Path, backup_dir: Path | None, had_files: set[str]) -> None:
    for filename in _ARTIFACT_FILES:
        destination = model_dir / filename
        source = backup_dir / filename if backup_dir is not None else None
        if source is not None and source.is_file():
            shutil.copy2(source, destination)
        elif filename not in had_files and destination.exists():
            destination.unlink()


def train_oos(
    source: str | Path,
    model_dir: str | Path = "models",
    horizon: int = 3,
    buy_threshold: float = 0.001,
    sell_threshold: float = -0.001,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    min_validation_f1: float = 0.35,
    min_oos_sharpe: float = 0.5,
    max_brier: float = 0.2,
    *,
    seed: int = 42,
    walk_forward_folds: int = 3,
    purge_gap: int | None = None,
    embargo: int | None = None,
    transaction_cost_bps: float = 10.0,
    slippage_bps: float = 5.0,
    max_ece: float = 0.10,
    registry_store: ModelRegistryStore | None = None,
    report_path: str | Path = "docs/reports/model-validation-latest.md",
) -> Dict[str, Any]:
    """Treina candidato; promoção exige gates legados e walk-forward mais estrito.

    Custos/slippage default são somente pressupostos explícitos para comparação,
    não estimativas para um ativo específico. O artefato só entra em model_dir
    depois de passar os gates e ser registrado no ModelRegistry.
    """
    horizon = int(horizon)
    if horizon < 1:
        raise ValueError("horizon deve ser >= 1 candle")
    if not np.isfinite([buy_threshold, sell_threshold]).all() or float(sell_threshold) >= float(buy_threshold):
        raise ValueError("thresholds devem ser finitos e sell_threshold < buy_threshold")
    if int(walk_forward_folds) < 2:
        raise ValueError("walk_forward_folds deve ser >= 2")
    purge = horizon if purge_gap is None else int(purge_gap)
    embargo_rows = horizon if embargo is None else int(embargo)
    if purge < horizon or embargo_rows < horizon:
        raise ValueError("purge_gap e embargo devem ser >= horizon para impedir sobreposição de labels")
    if not np.isfinite([transaction_cost_bps, slippage_bps]).all() or transaction_cost_bps < 0 or slippage_bps < 0:
        raise ValueError("custos e slippage devem ser finitos e não negativos")
    if not np.isfinite([min_validation_f1, min_oos_sharpe, max_brier, max_ece]).all():
        raise ValueError("limiares de promoção devem ser finitos")
    if not 0 <= float(min_validation_f1) <= 1 or not 0 <= float(max_brier) <= 2 or not 0 <= float(max_ece) <= 1:
        raise ValueError("limiares de classificação/calibração fora dos limites")
    if not np.isfinite([train_fraction, validation_fraction]).all():
        raise ValueError("frações de treino/validação devem ser finitas")
    if not 0.4 <= float(train_fraction) <= 0.8 or not 0.1 <= float(validation_fraction) <= 0.4:
        raise ValueError("frações de treino/validação fora dos limites seguros")
    if int(seed) < 0:
        raise ValueError("seed deve ser não negativo")
    if float(train_fraction) + float(validation_fraction) >= 1.0:
        raise ValueError("treino + validação precisa deixar bloco de teste não vazio")
    ohlcv = load_ohlcv(source)
    dataset_integrity = validate_ohlcv(ohlcv, require_closed=True, reject_gaps=False, min_coverage=0.95)
    dataset_sha256 = sha256_file(source) if Path(source).is_file() else sha256_frame(ohlcv)
    pipeline = FeaturePipeline()
    features, labels = pipeline.build_supervised(ohlcv, horizon, buy_threshold, sell_threshold)
    if len(features) < 180:
        raise ValueError("dataset OOS insuficiente; são necessárias pelo menos 180 amostras")
    train_cut = int(len(features) * train_fraction)
    valid_cut = int(len(features) * (train_fraction + validation_fraction))
    train_end = train_cut - max(1, int(horizon))
    valid_end = valid_cut - horizon
    if train_end < 60 or valid_end <= train_cut or len(features) <= valid_cut:
        raise ValueError("divisão OOS cronológica insuficiente")

    X_train, y_train = features.iloc[:train_end], labels.iloc[:train_end]
    X_valid, y_valid = features.iloc[train_cut:valid_end], labels.iloc[train_cut:valid_end]
    X_test, y_test = features.iloc[valid_cut:], labels.iloc[valid_cut:]
    close = pd.to_numeric(ohlcv["close"], errors="coerce")
    future_return = close.shift(-horizon) / close - 1.0
    forward_valid = future_return.reindex(X_valid.index).fillna(0.0)
    forward_test = future_return.reindex(X_test.index).fillna(0.0)
    model_path = Path(model_dir)
    model_path.mkdir(parents=True, exist_ok=True)
    metadata_path = model_path / "ensemble_metadata.json"
    previous_metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_metadata = {}

    walk_forward_metrics = evaluate_walk_forward(
        ohlcv,
        horizon=horizon,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        folds=walk_forward_folds,
        purge_gap=purge,
        embargo=embargo_rows,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
        seed=seed,
    )
    # Uma única identificação canônica por arquivo acompanha treino e relatório.
    walk_forward_metrics["dataset_sha256"] = dataset_sha256
    validation_report_path = write_validation_report(walk_forward_metrics, report_path)

    registry = registry_store
    owned_db_manager = None
    if registry is None:
        registry, owned_db_manager = _default_registry_store()
    previous_registry_version = registry.active_version("ensemble")
    model_version = f"ensemble-{dataset_sha256[:12]}-s{int(seed)}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    backup_dir: Path | None = None
    had_files = {filename for filename in _ARTIFACT_FILES if (model_path / filename).is_file()}

    try:
        with tempfile.TemporaryDirectory(prefix="zia-ensemble-") as temp_dir:
            candidate = EnsembleModel(temp_dir, random_state=seed)
            drift_reference = build_drift_reference(X_train)
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
                    "purge_gap": horizon if purge_gap is None else int(purge_gap),
                    "embargo": horizon if embargo is None else int(embargo),
                    "seed": int(seed),
                    "dataset_sha256": dataset_sha256,
                    "train_rows": len(X_train),
                    "validation_rows": len(X_valid),
                    "test_rows": len(X_test),
                    "neural_models": "not trained by this controlled Ensemble pipeline",
                    "drift_reference": drift_reference,
                },
            )
            valid_probabilities = candidate.predict_proba(X_valid)
            test_probabilities = candidate.predict_proba(X_test)
            valid_predictions = _predict(candidate, X_valid)
            test_predictions = _predict(candidate, X_test)
            valid_metrics = _metrics(y_valid, valid_predictions, forward_valid)
            test_metrics = _metrics(y_test, test_predictions, forward_test)
            valid_calibration = probability_metrics(y_valid.to_numpy(dtype=int), valid_probabilities)
            test_calibration = probability_metrics(y_test.to_numpy(dtype=int), test_probabilities)
            candidate_metadata["validation_metrics"] = valid_metrics
            candidate_metadata["test_metrics"] = test_metrics
            candidate_metadata["validation_calibration"] = valid_calibration
            candidate_metadata["calibration"] = test_calibration
            candidate_metadata["calibration_brier"] = test_calibration["brier_score"]
            candidate_metadata["calibration_ece"] = test_calibration["ece"]
            candidate_metadata["dataset_integrity"] = dataset_integrity
            candidate_metadata["walk_forward_metrics"] = walk_forward_metrics
            candidate_metadata["model_version"] = model_version
            candidate_metadata["report_path"] = str(validation_report_path)

            previous_f1 = float((previous_metadata.get("validation_metrics") or {}).get("f1_macro", -1.0))
            wf_aggregate = walk_forward_metrics["aggregate"]
            accepted = (
                valid_metrics["f1_macro"] >= float(min_validation_f1)
                and test_metrics["sharpe_proxy"] > float(min_oos_sharpe)
                and valid_calibration["brier_score"] < float(max_brier)
                and valid_calibration["ece"] <= float(max_ece)
                and test_calibration["brier_score"] < float(max_brier)
                and test_calibration["ece"] <= float(max_ece)
                and wf_aggregate["model_classification"]["brier_score"] < float(max_brier)
                and wf_aggregate["model_classification"]["ece"] <= float(max_ece)
                and bool(wf_aggregate["outperforms_all_baselines"])
                and (previous_f1 < 0.0 or valid_metrics["f1_macro"] > previous_f1)
            )
            candidate_metadata["decision"] = "accepted" if accepted else "rejected"
            candidate_metadata["registry_status"] = "active" if accepted else "rejected"
            candidate_metadata["metrics_oos"] = {
                "validation": valid_metrics,
                "test": test_metrics,
                "validation_calibration": valid_calibration,
                "test_calibration": test_calibration,
                "walk_forward": walk_forward_metrics,
            }
            candidate_metadata["training_config"] = {
                "seed": int(seed),
                "horizon": int(horizon),
                "buy_threshold": float(buy_threshold),
                "sell_threshold": float(sell_threshold),
                "walk_forward_folds": int(walk_forward_folds),
                "purge_gap": horizon if purge_gap is None else int(purge_gap),
                "embargo": horizon if embargo is None else int(embargo),
                "transaction_cost_bps": float(transaction_cost_bps),
                "slippage_bps": float(slippage_bps),
                "min_validation_f1": float(min_validation_f1),
                "min_oos_sharpe": float(min_oos_sharpe),
                "max_brier": float(max_brier),
                "max_ece": float(max_ece),
            }

            if accepted:
                backup_dir = model_path / f"rollback_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
                backup_dir.mkdir(parents=True, exist_ok=False)
                for filename in _ARTIFACT_FILES:
                    current = model_path / filename
                    if current.is_file():
                        shutil.copy2(current, backup_dir / filename)
                candidate_metadata["rollback_backup"] = str(backup_dir.resolve())
                candidate_metadata["rollback_backup_sha256"] = (
                    artifact_sha256(backup_dir) if all((backup_dir / name).is_file() for name in _ARTIFACT_FILES) else None
                )
                candidate_metadata["rollback_version"] = previous_registry_version
            (Path(temp_dir) / "ensemble_metadata.json").write_text(
                json.dumps(candidate_metadata, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8"
            )
            candidate_artifact_hash = artifact_sha256(temp_dir)
            registry_metrics = candidate_metadata["metrics_oos"]
            training_config = {
                **candidate_metadata["training_config"],
                "artifact_directory": str(model_path.resolve()) if accepted else None,
                "artifact_persisted": bool(accepted),
                "rollback_backup": str(backup_dir.resolve()) if backup_dir else None,
                "rollback_backup_sha256": candidate_metadata.get("rollback_backup_sha256"),
                "rollback_version": previous_registry_version,
                "feature_columns": list(candidate_metadata.get("feature_columns", [])),
            }
            registry.register(
                model_name="ensemble",
                version=model_version,
                artifact_hash=candidate_artifact_hash,
                dataset_hash=dataset_sha256,
                metrics_oos=registry_metrics,
                training_config=training_config,
                status="candidate" if accepted else "rejected",
            )

            if accepted:
                try:
                    for filename in _ARTIFACT_FILES:
                        shutil.copy2(Path(temp_dir) / filename, model_path / filename)
                    if artifact_sha256(model_path) != candidate_artifact_hash:
                        raise RuntimeError("hash dos artefatos copiados diverge do registro candidato")
                    registry.activate(model_version)
                except Exception:
                    _restore_previous_files(model_path, backup_dir, had_files)
                    try:
                        registry.set_status(model_version, "rejected")
                    except Exception:
                        pass
                    raise
            return candidate_metadata
    finally:
        if owned_db_manager is not None:
            owned_db_manager.engine.dispose()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--buy-threshold", type=float, default=0.001)
    parser.add_argument("--sell-threshold", type=float, default=-0.001)
    parser.add_argument("--min-validation-f1", type=float, default=0.35)
    parser.add_argument("--min-oos-sharpe", type=float, default=0.5)
    parser.add_argument("--max-brier", type=float, default=0.2)
    parser.add_argument("--max-ece", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--walk-forward-folds", type=int, default=3)
    parser.add_argument("--purge-gap", type=int)
    parser.add_argument("--embargo", type=int)
    parser.add_argument("--transaction-cost-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--report-path", default="docs/reports/model-validation-latest.md")
    args = parser.parse_args()
    result = train_oos(
        args.dataset,
        model_dir=args.model_dir,
        horizon=args.horizon,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        min_validation_f1=args.min_validation_f1,
        min_oos_sharpe=args.min_oos_sharpe,
        max_brier=args.max_brier,
        max_ece=args.max_ece,
        seed=args.seed,
        walk_forward_folds=args.walk_forward_folds,
        purge_gap=args.purge_gap,
        embargo=args.embargo,
        transaction_cost_bps=args.transaction_cost_bps,
        slippage_bps=args.slippage_bps,
        report_path=args.report_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
