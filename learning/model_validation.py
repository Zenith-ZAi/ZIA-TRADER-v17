"""Validação temporal conservadora do Ensemble; não promove modelos."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from ai.ensemble_model import EnsembleModel
from core.dataset_integrity import sha256_frame, validate_ohlcv
from core.feature_pipeline import FeaturePipeline


ACTION_BY_CLASS = {0: "sell", 1: "hold", 2: "buy"}


def make_walk_forward_splits(
    n_rows: int,
    *,
    folds: int = 3,
    min_train_rows: int | None = None,
    purge_gap: int = 3,
    embargo: int = 3,
) -> list[dict[str, int]]:
    """Expanding windows strictly past-only, with purge/embargo buffers.

    Train contains rows strictly before ``test_start - purge_gap - embargo``.
    Test blocks are separated by an embargo window. Each row is scored once at
    most and adjacent forward-return labels cannot overlap the test boundary.
    """
    n_rows = int(n_rows)
    folds = int(folds)
    purge_gap = int(purge_gap)
    embargo = int(embargo)
    if n_rows < 1 or folds < 2 or purge_gap < 0 or embargo < 0:
        raise ValueError("n_rows/folds/gaps inválidos; folds precisa ser >= 2")
    min_train = int(min_train_rows if min_train_rows is not None else max(60, n_rows // 2))
    if min_train < 1:
        raise ValueError("min_train_rows deve ser positivo")
    first_test_start = min_train + purge_gap + embargo
    test_rows = (n_rows - first_test_start - embargo * (folds - 1)) // folds
    if test_rows < 1:
        raise ValueError("dataset insuficiente para folds, purge e embargo solicitados")
    splits = []
    for fold in range(folds):
        test_start = first_test_start + fold * (test_rows + embargo)
        test_end = min(n_rows, test_start + test_rows)
        train_end = test_start - purge_gap - embargo
        if train_end < min_train or test_end <= test_start:
            raise ValueError("fold temporal não satisfaz treino mínimo/purge/embargo")
        splits.append({
            "fold": fold + 1,
            "train_start": 0,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "purge_gap": purge_gap,
            "embargo": embargo,
        })
    return splits


def probability_metrics(y_true: np.ndarray | pd.Series, probabilities: np.ndarray) -> dict[str, Any]:
    """Brier multiclasses, ECE top-label e pontos da reliability curve."""
    truth = np.asarray(y_true, dtype=int).reshape(-1)
    probs = np.asarray(probabilities, dtype=float)
    if probs.ndim != 2 or probs.shape != (len(truth), 3) or len(truth) == 0:
        raise ValueError("probabilidades devem ter shape (n, 3), alinhadas a y")
    if not np.isfinite(probs).all() or (probs < 0).any() or (probs > 1).any():
        raise ValueError("probabilidades não finitas ou fora de [0,1]")
    row_sums = probs.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-6):
        raise ValueError("probabilidades multiclasses precisam somar 1")
    predicted = probs.argmax(axis=1)
    confidence = probs.max(axis=1)
    correct = (predicted == truth).astype(float)
    one_hot = np.eye(3, dtype=float)[truth]
    brier = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))
    bins = np.linspace(0.0, 1.0, 11)
    curve = []
    ece = 0.0
    for index in range(len(bins) - 1):
        lower, upper = float(bins[index]), float(bins[index + 1])
        mask = (confidence >= lower) & (confidence < upper if index < len(bins) - 2 else confidence <= upper)
        count = int(mask.sum())
        if count:
            mean_confidence = float(confidence[mask].mean())
            accuracy = float(correct[mask].mean())
            ece += count / len(truth) * abs(accuracy - mean_confidence)
        else:
            mean_confidence = None
            accuracy = None
        curve.append({"lower": lower, "upper": upper, "count": count, "mean_confidence": mean_confidence, "accuracy": accuracy})
    return {
        "brier_score": brier,
        "ece": float(ece),
        "reliability_curve": curve,
        "accuracy": float(correct.mean()),
        "balanced_accuracy": float(np.mean([np.mean(predicted[truth == label] == label) for label in np.unique(truth)])),
        "f1_macro": float(f1_score(truth, predicted, labels=[0, 1, 2], average="macro", zero_division=0)),
        "rows": int(len(truth)),
    }


def _net_returns(positions: np.ndarray, forward_returns: np.ndarray, total_cost_bps: float) -> tuple[np.ndarray, np.ndarray]:
    positions = np.asarray(positions, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)
    if positions.ndim != 1 or forward_returns.shape != positions.shape:
        raise ValueError("positions e forward_returns devem ser vetores alinhados")
    if not np.isfinite(positions).all() or not np.isfinite(forward_returns).all():
        raise ValueError("positions/forward_returns contêm valores não finitos")
    if not np.isin(positions, [-1.0, 0.0, 1.0]).all():
        raise ValueError("positions deve conter somente -1, 0 ou 1")
    if not np.isfinite(total_cost_bps) or float(total_cost_bps) < 0:
        raise ValueError("total_cost_bps deve ser finito e não negativo")
    cost_rate = float(total_cost_bps) / 10_000.0
    net = np.empty(len(positions), dtype=float)
    trade_counts = np.zeros(len(positions), dtype=int)
    previous = 0.0
    for index, (position, result) in enumerate(zip(positions, forward_returns)):
        turnover = abs(float(position) - previous)
        trade_counts[index] += int(turnover > 0)
        net[index] = float(position) * float(result) - turnover * cost_rate
        previous = float(position)
    if len(net) and previous:
        net[-1] -= abs(previous) * cost_rate  # liquidação do último bloco OOS
        trade_counts[-1] += 1
    return net, trade_counts


def _return_summary(values: list[float], trades: int) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    return {
        "blocks": int(array.size),
        "trades": int(trades),
        "cumulative_net_return": float(array.sum()) if array.size else 0.0,
        "mean_net_block_return": float(array.mean()) if array.size else 0.0,
        "win_rate": float((array > 0).mean()) if array.size else 0.0,
        "worst_block_return": float(array.min()) if array.size else 0.0,
    }


def _regime_labels(close: pd.Series, train_index: pd.Index, sample_index: pd.Index, buy_threshold: float, sell_threshold: float) -> tuple[pd.Series, float]:
    numeric_close = pd.to_numeric(close, errors="coerce").astype(float)
    returns = numeric_close.pct_change()
    volatility = returns.rolling(20, min_periods=20).std(ddof=0)
    training_vol = volatility.reindex(train_index).dropna()
    cutoff = float(training_vol.median()) if not training_vol.empty else 0.0
    momentum = numeric_close.pct_change(20)
    labels: dict[Any, str] = {}
    for stamp in sample_index:
        vol = volatility.get(stamp, np.nan)
        trend_return = momentum.get(stamp, np.nan)
        vol_label = "high_vol" if np.isfinite(vol) and float(vol) > cutoff else "low_vol"
        if not np.isfinite(trend_return):
            trend_label = "unknown_trend"
        elif float(trend_return) >= buy_threshold:
            trend_label = "uptrend"
        elif float(trend_return) <= sell_threshold:
            trend_label = "downtrend"
        else:
            trend_label = "sideways"
        labels[stamp] = f"{vol_label}_{trend_label}"
    return pd.Series(labels), cutoff


def _aggregate_regimes(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for regime in sorted({row["regime"] for row in records}):
        subset = [row for row in records if row["regime"] == regime]
        truths = np.asarray([row["truth"] for row in subset], dtype=int)
        probs = np.asarray([row["probabilities"] for row in subset], dtype=float)
        strategies = {}
        for key in ("model_net", "buy_hold_net", "deterministic_net"):
            strategies[key] = _return_summary([row[key] for row in subset], sum(row[f"{key}_trades"] for row in subset))
        result[regime] = {
            "rows": len(subset),
            "model_classification": probability_metrics(truths, probs),
            "strategies": strategies,
        }
    return result


def evaluate_walk_forward(
    ohlcv: pd.DataFrame,
    *,
    horizon: int = 3,
    buy_threshold: float = 0.001,
    sell_threshold: float = -0.001,
    folds: int = 3,
    min_train_rows: int | None = None,
    purge_gap: int | None = None,
    embargo: int | None = None,
    transaction_cost_bps: float,
    slippage_bps: float,
    seed: int = 42,
    model_factory: Callable[[str, int], Any] | None = None,
) -> dict[str, Any]:
    """Avalia modelos em janelas futuras; não escreve, ativa ou promove artefatos."""
    horizon = int(horizon)
    if horizon < 1:
        raise ValueError("horizon deve ser >= 1 candle")
    if not np.isfinite([buy_threshold, sell_threshold]).all() or float(sell_threshold) >= float(buy_threshold):
        raise ValueError("thresholds devem ser finitos e sell_threshold < buy_threshold")
    if not np.isfinite([transaction_cost_bps, slippage_bps]).all() or transaction_cost_bps < 0 or slippage_bps < 0:
        raise ValueError("custos e slippage devem ser finitos e não negativos")
    if int(seed) < 0:
        raise ValueError("seed deve ser não negativo")
    purge = int(horizon if purge_gap is None else purge_gap)
    embargo_rows = int(horizon if embargo is None else embargo)
    if purge < horizon or embargo_rows < horizon:
        raise ValueError("purge_gap e embargo devem ser >= horizon para impedir sobreposição de labels")
    integrity = validate_ohlcv(ohlcv, require_closed=True, reject_gaps=False, min_coverage=0.95)
    features, labels = FeaturePipeline().build_supervised(ohlcv, horizon, buy_threshold, sell_threshold)
    if len(features) != len(labels) or len(features) < 180:
        raise ValueError("dataset supervisionado insuficiente/alinhamento inválido para walk-forward")
    splits = make_walk_forward_splits(
        len(features), folds=folds, min_train_rows=min_train_rows, purge_gap=purge, embargo=embargo_rows
    )
    close = pd.to_numeric(ohlcv["close"], errors="coerce").astype(float)
    forward_return = close.shift(-horizon) / close - 1.0
    total_cost_bps = float(transaction_cost_bps) + float(slippage_bps)
    factory = model_factory or (lambda directory, model_seed: EnsembleModel(directory, random_state=model_seed))
    all_records: list[dict[str, Any]] = []
    fold_reports = []

    for split in splits:
        train_start, train_end = split["train_start"], split["train_end"]
        test_start, test_end = split["test_start"], split["test_end"]
        X_train, y_train = features.iloc[train_start:train_end], labels.iloc[train_start:train_end]
        # Non-overlapping horizon blocks prevent repeated returns from inflating OOS metrics.
        sample_positions = np.arange(test_start, test_end, max(1, int(horizon)), dtype=int)
        X_test = features.iloc[sample_positions]
        y_test = labels.iloc[sample_positions].to_numpy(dtype=int)
        if len(X_train) < 60 or len(X_test) < 5:
            raise ValueError(f"fold {split['fold']} sem amostras suficientes após purge/embargo")
        with tempfile.TemporaryDirectory(prefix=f"zia-wf-{split['fold']}-") as model_dir:
            model = factory(model_dir, int(seed) + split["fold"] - 1)
            model.train(
                X_train,
                y_train,
                metadata={
                    "validation": "walk_forward",
                    "fold": split["fold"],
                    "seed": int(seed) + split["fold"] - 1,
                    "purge_gap": purge,
                    "embargo": embargo_rows,
                },
            )
            probabilities = np.asarray(model.predict_proba(X_test), dtype=float)
        probability_report = probability_metrics(y_test, probabilities)
        prediction = probabilities.argmax(axis=1)
        model_position = np.where(prediction == 2, 1.0, np.where(prediction == 0, -1.0, 0.0))
        buy_hold_position = np.ones(len(X_test), dtype=float)
        sample_close_returns = forward_return.reindex(X_test.index).to_numpy(dtype=float)
        if not np.isfinite(sample_close_returns).all():
            raise ValueError(f"fold {split['fold']} contém forward return não finito")
        momentum = close.pct_change(20).reindex(X_test.index).to_numpy(dtype=float)
        deterministic_position = np.where(
            momentum >= buy_threshold, 1.0,
            np.where(momentum <= sell_threshold, -1.0, 0.0),
        )
        model_net, model_trade_counts = _net_returns(model_position, sample_close_returns, total_cost_bps)
        buy_hold_net, buy_hold_trade_counts = _net_returns(buy_hold_position, sample_close_returns, total_cost_bps)
        deterministic_net, deterministic_trade_counts = _net_returns(deterministic_position, sample_close_returns, total_cost_bps)
        regimes, volatility_cutoff = _regime_labels(close, features.index[:train_end], X_test.index, buy_threshold, sell_threshold)
        for row_index, stamp in enumerate(X_test.index):
            all_records.append({
                "fold": split["fold"],
                "timestamp": str(stamp),
                "regime": str(regimes.loc[stamp]),
                "truth": int(y_test[row_index]),
                "probabilities": probabilities[row_index].tolist(),
                "model_net": float(model_net[row_index]),
                "model_net_trades": int(model_trade_counts[row_index]),
                "buy_hold_net": float(buy_hold_net[row_index]),
                "buy_hold_net_trades": int(buy_hold_trade_counts[row_index]),
                "deterministic_net": float(deterministic_net[row_index]),
                "deterministic_net_trades": int(deterministic_trade_counts[row_index]),
            })
        fold_reports.append({
            **split,
            "train_rows": int(len(X_train)),
            "scored_rows": int(len(X_test)),
            "train_timestamp_start": str(X_train.index[0]),
            "train_timestamp_end": str(X_train.index[-1]),
            "test_timestamp_start": str(X_test.index[0]),
            "test_timestamp_end": str(X_test.index[-1]),
            "training_volatility_median": volatility_cutoff,
            "model_classification": probability_report,
            "strategies": {
                "model": _return_summary(model_net.tolist(), int(model_trade_counts.sum())),
                "buy_and_hold": _return_summary(buy_hold_net.tolist(), int(buy_hold_trade_counts.sum())),
                "deterministic_momentum": _return_summary(deterministic_net.tolist(), int(deterministic_trade_counts.sum())),
            },
        })

    truths_all = np.asarray([row["truth"] for row in all_records], dtype=int)
    probabilities_all = np.asarray([row["probabilities"] for row in all_records], dtype=float)
    aggregate_strategies = {}
    for key, trade_key in (("model", "model_net_trades"), ("buy_and_hold", "buy_hold_net_trades"), ("deterministic_momentum", "deterministic_net_trades")):
        net_key = {"model": "model_net", "buy_and_hold": "buy_hold_net", "deterministic_momentum": "deterministic_net"}[key]
        aggregate_strategies[key] = _return_summary(
            [row[net_key] for row in all_records], sum(row[trade_key] for row in all_records)
        )
    model_return = aggregate_strategies["model"]["cumulative_net_return"]
    baseline_returns = {
        "buy_and_hold": aggregate_strategies["buy_and_hold"]["cumulative_net_return"],
        "deterministic_momentum": aggregate_strategies["deterministic_momentum"]["cumulative_net_return"],
    }
    return {
        "schema_version": 1,
        "dataset_sha256": sha256_frame(ohlcv),
        "dataset_integrity": integrity,
        "seed": int(seed),
        "folds": fold_reports,
        "aggregate": {
            "scored_rows": int(len(all_records)),
            "model_classification": probability_metrics(truths_all, probabilities_all),
            "strategies": aggregate_strategies,
            "baseline_net_returns": baseline_returns,
            "outperforms_all_baselines": bool(all(model_return > value for value in baseline_returns.values())),
        },
        "by_regime": _aggregate_regimes(all_records),
        "assumptions": {
            "horizon_bars": int(horizon),
            "purge_gap_rows": purge,
            "embargo_rows": embargo_rows,
            "transaction_cost_bps_per_unit_turnover": float(transaction_cost_bps),
            "slippage_bps_per_unit_turnover": float(slippage_bps),
            "combined_cost_bps": total_cost_bps,
            "return_blocks": "non-overlapping horizon blocks; fixed notional; arithmetic net-return sum",
            "buy_and_hold": "long-only, entry/exit costs included",
            "deterministic_baseline": "past-only 20-bar momentum; short return is hypothetical and excludes borrow/funding",
            "regime": "20-bar realized volatility split at train-only median; trend from trailing 20-bar return",
            "promotion": "this evaluator never promotes; caller must apply all independent gates",
        },
    }


def write_validation_report(report: dict[str, Any], destination: str | Path) -> Path:
    """Escreve um relatório Markdown reproduzível, sem incluir séries de preços."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    aggregate = report["aggregate"]
    strategy_lines = [
        "| Comparador | Retorno líquido cumulativo | Blocos | Trades |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metrics in aggregate["strategies"].items():
        strategy_lines.append(
            f"| {name} | {metrics['cumulative_net_return']:.6f} | {metrics['blocks']} | {metrics['trades']} |"
        )
    regime_lines = [
        "| Regime | Amostras | F1 macro | Brier | ECE | Modelo líquido | Buy & hold | Momentum |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for regime, metrics in report["by_regime"].items():
        classification = metrics["model_classification"]
        strategies = metrics["strategies"]
        regime_lines.append(
            f"| {regime} | {metrics['rows']} | {classification['f1_macro']:.4f} | "
            f"{classification['brier_score']:.4f} | {classification['ece']:.4f} | "
            f"{strategies['model_net']['cumulative_net_return']:.6f} | "
            f"{strategies['buy_hold_net']['cumulative_net_return']:.6f} | "
            f"{strategies['deterministic_net']['cumulative_net_return']:.6f} |"
        )
    calibration = aggregate["model_classification"]
    assumptions_json = json.dumps(report["assumptions"], ensure_ascii=False, indent=2, sort_keys=True)
    lines = [
        "# Relatório walk-forward do Ensemble",
        "",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Seed: {report['seed']}; folds: {len(report['folds'])}",
        f"- Integridade: {report['dataset_integrity']['rows']} candles, "
        f"{report['dataset_integrity']['first_timestamp']} a {report['dataset_integrity']['last_timestamp']}",
        f"- Resultado comparativo: `{'supera baselines' if aggregate['outperforms_all_baselines'] else 'não supera todos os baselines'}`",
        f"- Amostras OOS não sobrepostas: {aggregate['scored_rows']}",
        f"- Brier multiclasses: {calibration['brier_score']:.6f}",
        f"- ECE top-label: {calibration['ece']:.6f}",
        "",
        "## Retorno OOS líquido e baselines",
        "",
        *strategy_lines,
        "",
        "## Janelas walk-forward",
        "",
        "| Fold | Treino até | Teste de | Teste até | Treino rows | OOS rows | Purge | Embargo |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {fold['fold']} | {fold['train_timestamp_end']} | {fold['test_timestamp_start']} | "
            f"{fold['test_timestamp_end']} | {fold['train_rows']} | {fold['scored_rows']} | "
            f"{fold['purge_gap']} | {fold['embargo']} |"
            for fold in report["folds"]
        ],
        "",
        "## Métricas por regime",
        "",
        *regime_lines,
        "",
        "## Reliability curve",
        "",
        "| Faixa de confiança | Contagem | Confiança média | Acurácia observada |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in calibration["reliability_curve"]:
        conf = "n/a" if row["mean_confidence"] is None else f"{row['mean_confidence']:.4f}"
        accuracy = "n/a" if row["accuracy"] is None else f"{row['accuracy']:.4f}"
        lines.append(f"| [{row['lower']:.1f}, {row['upper']:.1f}] | {row['count']} | {conf} | {accuracy} |")
    lines.extend([
        "",
        "## Protocolo e pressupostos",
        "",
        "```json",
        assumptions_json,
        "```",
        "",
        "Este relatório é avaliação OOS, não recomendação de investimento nem autorização de execução. Short é um comparador hipotético sem borrow/funding; custos devem ser ajustados ao instrumento e venue antes de qualquer análise real.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
