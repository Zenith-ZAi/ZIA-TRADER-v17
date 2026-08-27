from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd


class DatasetIntegrityError(ValueError):
    """Dataset não pode ser usado para replay/backtest auditável."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_frame(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    payload = normalized.sort_index().to_csv(index=True, date_format="%Y-%m-%dT%H:%M:%S.%fZ").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_ohlcv(
    frame: pd.DataFrame,
    *,
    timeframe: str | None = None,
    require_closed: bool = True,
    reject_gaps: bool = False,
    min_coverage: float = 0.95,
) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise DatasetIntegrityError("dataset OHLCV vazio")
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise DatasetIntegrityError(f"colunas OHLCV ausentes: {missing}")
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        if "open_time" in frame.columns:
            index = pd.DatetimeIndex(pd.to_datetime(frame["open_time"], utc=True))
        elif "timestamp" in frame.columns:
            index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
        else:
            raise DatasetIntegrityError("dataset precisa de índice temporal ou open_time/timestamp")
    index = pd.DatetimeIndex(index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    if not index.is_monotonic_increasing:
        raise DatasetIntegrityError("timestamps fora de ordem crescente")
    if index.duplicated().any():
        raise DatasetIntegrityError("timestamps duplicados")
    numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise DatasetIntegrityError("dataset contém valores OHLCV não numéricos ou nulos")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric["volume"] < 0).any():
        raise DatasetIntegrityError("dataset contém preços não positivos ou volume negativo")
    if (numeric["high"] < numeric[["open", "close"]].max(axis=1)).any() or (numeric["low"] > numeric[["open", "close"]].min(axis=1)).any():
        raise DatasetIntegrityError("high/low incompatíveis com open/close")
    if require_closed:
        now = pd.Timestamp.now(tz="UTC")
        if index[-1] >= now:
            raise DatasetIntegrityError("último candle ainda não está fechado")
    expected_ms = None
    if timeframe:
        values = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}
        expected_ms = values.get(str(timeframe))
    gaps = 0
    expected_rows = int(len(index))
    coverage_ratio = 1.0
    if expected_ms and len(index) > 1:
        deltas = pd.Series(index[1:] - index[:-1]).dt.total_seconds().mul(1000)
        gaps = int((deltas != expected_ms).sum())
        expected_rows = int(round((index[-1] - index[0]).total_seconds() * 1000 / expected_ms)) + 1
        coverage_ratio = min(1.0, float(len(index)) / max(expected_rows, 1))
        if reject_gaps and gaps:
            raise DatasetIntegrityError(f"dataset contém {gaps} gaps para timeframe {timeframe}")
        if coverage_ratio < float(min_coverage):
            raise DatasetIntegrityError(f"cobertura {coverage_ratio:.4f} abaixo do mínimo {float(min_coverage):.4f}")
    return {
        "rows": int(len(frame)),
        "expected_rows": expected_rows,
        "coverage_ratio": coverage_ratio,
        "first_timestamp": index[0].isoformat(),
        "last_timestamp": index[-1].isoformat(),
        "duplicates": 0,
        "gaps": gaps,
        "timeframe": timeframe,
        "closed": bool(require_closed),
    }
