"""Entrada de treino OHLCV delegada ao pipeline controlado de MLOps."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd


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
    *,
    seed: int = 42,
    transaction_cost_bps: float = 10.0,
    slippage_bps: float = 5.0,
    report_path: str | Path = "docs/reports/model-validation-latest.md",
) -> Dict[str, Any]:
    """Compatibilidade de API/CLI; não treina nem grava artefatos diretamente."""
    from learning.training_pipeline import train_oos

    return train_oos(
        source,
        model_dir=model_dir,
        horizon=horizon,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        seed=seed,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
        report_path=report_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--buy-threshold", type=float, default=0.001)
    parser.add_argument("--sell-threshold", type=float, default=-0.001)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--transaction-cost-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--report-path", default="docs/reports/model-validation-latest.md")
    args = parser.parse_args()
    result = train_from_ohlcv(
        args.dataset,
        model_dir=args.model_dir,
        horizon=args.horizon,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        seed=args.seed,
        transaction_cost_bps=args.transaction_cost_bps,
        slippage_bps=args.slippage_bps,
        report_path=args.report_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
