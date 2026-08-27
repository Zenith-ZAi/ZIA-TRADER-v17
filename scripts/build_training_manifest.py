"""Gera manifesto imutável de treino/teste; não baixa nem fabrica dados."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dataset_integrity import sha256_file, validate_ohlcv

REQUIRED_ASSETS = {"BTCUSDT", "ETHUSDT", "EURUSD", "SPY"}


def inspect_asset(asset: str, path: Path, timeframe: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"dataset ausente: {asset} -> {path}")
    frame = pd.read_csv(path, parse_dates=["open_time"])
    integrity = validate_ohlcv(frame, timeframe=timeframe, require_closed=True, reject_gaps=False, min_coverage=0.95)
    timestamps = pd.to_datetime(frame["open_time"], utc=True)
    train = timestamps[(timestamps.dt.year >= 2018) & (timestamps.dt.year <= 2023)]
    test = timestamps[(timestamps.dt.year >= 2024) & (timestamps.dt.year <= 2026)]
    if train.empty or test.empty:
        raise ValueError(f"{asset}: as janelas 2018-2023 e 2024-2026 precisam conter dados")
    return {
        "asset": asset,
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": int(len(frame)),
        "start": timestamps.min().isoformat(),
        "end": timestamps.max().isoformat(),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "integrity": integrity,
    }


def build_manifest(paths: dict[str, Path], timeframe: str) -> dict[str, Any]:
    missing = sorted(REQUIRED_ASSETS - set(paths))
    if missing:
        raise ValueError(f"ativos obrigatórios ausentes: {missing}")
    assets = [inspect_asset(asset, paths[asset], timeframe) for asset in sorted(REQUIRED_ASSETS)]
    return {
        "manifest_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "train_window": {"start": "2018-01-01T00:00:00Z", "end": "2023-12-31T23:59:59Z"},
        "test_window": {"start": "2024-01-01T00:00:00Z", "end": "2026-12-31T23:59:59Z"},
        "assets": assets,
        "immutable": True,
        "note": "Manifesto somente de arquivos fornecidos pelo operador; não contém dados nem segredos.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida e cria manifesto de treino/teste multiativo")
    parser.add_argument("--dataset", action="append", nargs=2, metavar=("ASSET", "PATH"), required=True)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--output", default="data/training_manifest.json")
    args = parser.parse_args()
    paths = {asset.upper(): Path(path) for asset, path in args.dataset}
    try:
        manifest = build_manifest(paths, args.timeframe)
    except (OSError, ValueError, KeyError) as exc:
        result = {"status": "blocked", "reason": str(exc), "immutable": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "output": str(output), "assets": len(manifest["assets"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
