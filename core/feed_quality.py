"""Validação de qualidade para históricos de feed usados pelo motor live.

O módulo não gera sinais. Ele rejeita séries inutilizáveis antes da etapa de análise.
Para B3/Forex, gaps só são inferidos dentro da mesma sessão; sem calendário oficial
(feriados/DST) não inventamos barras ausentes em períodos fechados.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

import pandas as pd

from core.dataset_integrity import DatasetIntegrityError, validate_ohlcv


TIMEFRAME_SECONDS: dict[str, int] = {
    "1s": 1,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
    "1wk": 604800,
}


class FeedQualityError(ValueError):
    """Série inválida para análise; ``incidents`` pode ser persistido como gap."""

    def __init__(self, message: str, incidents: list[dict[str, Any]]):
        super().__init__(message)
        self.incidents = incidents


def _utc_timestamp(value: datetime | pd.Timestamp | None) -> pd.Timestamp:
    stamp = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _session_date(stamp: pd.Timestamp, market: str) -> object | None:
    market = str(market or "crypto").lower()
    if market in {"b3", "stocks", "stock"}:
        local = stamp.tz_convert("America/Sao_Paulo")
        if local.weekday() >= 5 or not (time(9, 0) <= local.time() < time(18, 0)):
            return None
        return local.date()
    if market in {"forex", "fx"}:
        utc = stamp.tz_convert("UTC")
        current_time = utc.time()
        if utc.weekday() == 5:
            return None
        if utc.weekday() == 6 and current_time < time(22, 0):
            return None
        if utc.weekday() == 4 and current_time >= time(21, 0):
            return None
        return utc.date()
    return stamp.date()


def _base_incident(
    kind: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "gap_start": start.isoformat(),
        "gap_end": end.isoformat(),
        "details": details,
    }


def _integrity_incident(frame: pd.DataFrame, exc: DatasetIntegrityError, now: pd.Timestamp) -> dict[str, Any]:
    message = str(exc)
    if "duplicados" in message:
        kind = "duplicate_timestamp"
    elif "ordem" in message:
        kind = "out_of_order_timestamp"
    else:
        kind = "invalid_ohlcv"
    timestamp = now
    if isinstance(frame, pd.DataFrame) and isinstance(frame.index, pd.DatetimeIndex) and not frame.empty:
        try:
            timestamp = _utc_timestamp(frame.index[-1])
        except (TypeError, ValueError):
            pass
    return _base_incident(kind, timestamp, now, {"reason": message})


def assess_ohlcv_quality(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    market: str = "crypto",
    now: datetime | pd.Timestamp | None = None,
    staleness_multiplier: float = 3.0,
) -> dict[str, Any]:
    """Valida valores e frescor; gera erro diante de candle ausente em sessão.

    Crypto usa cadência 24/7. B3/Forex só contam gaps quando ambos os candles
    delimitadores estão na mesma sessão e no mesmo dia local/UTC, evitando
    confundir fechamento diário, fim de semana ou feriado com falha de feed.
    """
    current = _utc_timestamp(now)
    interval = TIMEFRAME_SECONDS.get(str(timeframe).strip().lower())
    if interval is None:
        incident = _base_incident(
            "unsupported_timeframe", current, current,
            {"timeframe": str(timeframe)},
        )
        raise FeedQualityError(f"timeframe não suportado para validação: {timeframe}", [incident])

    try:
        # Validador comum rejeita vazio, campos/valores inválidos, ordem e duplicatas.
        validate_ohlcv(
            frame,
            timeframe=str(timeframe) if str(timeframe) in {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"} else None,
            require_closed=False,
            reject_gaps=False,
            min_coverage=0.0,
        )
    except (DatasetIntegrityError, TypeError, ValueError, OverflowError) as exc:
        if not isinstance(exc, DatasetIntegrityError):
            exc = DatasetIntegrityError(f"timestamp/valores inválidos: {exc}")
        raise FeedQualityError(str(exc), [_integrity_incident(frame, exc, current)]) from exc

    if isinstance(frame.index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(frame.index)
    elif "open_time" in frame.columns:
        index = pd.DatetimeIndex(pd.to_datetime(frame["open_time"], utc=True))
    elif "timestamp" in frame.columns:
        index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    else:
        # O validador acima já rejeitaria esse caso; mantém o contrato explícito.
        incident = _base_incident("invalid_ohlcv", current, current, {"reason": "timestamp ausente"})
        raise FeedQualityError("dataset precisa de índice temporal ou coluna timestamp", [incident])
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    if len(index) == 0:
        incident = _base_incident("feed_unavailable", current, current, {"reason": "histórico vazio"})
        raise FeedQualityError("histórico OHLCV vazio", [incident])

    age_seconds = (current - index[-1]).total_seconds()
    max_age_seconds = interval * max(float(staleness_multiplier), 1.0)
    incidents: list[dict[str, Any]] = []
    if age_seconds < -1.0:
        incidents.append(_base_incident(
            "future_timestamp", index[-1], current,
            {"age_seconds": age_seconds, "reason": "último candle está no futuro"},
        ))
    elif age_seconds > max_age_seconds:
        incidents.append(_base_incident(
            "stale_feed", index[-1] + pd.Timedelta(seconds=interval), current,
            {"age_seconds": age_seconds, "max_age_seconds": max_age_seconds},
        ))

    market_name = str(market or "crypto").lower()
    is_continuous = market_name not in {"b3", "stocks", "stock", "forex", "fx"}
    missing: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    checked_intervals = 0
    for start, end in zip(index[:-1], index[1:]):
        delta = (end - start).total_seconds()
        if delta <= 0:
            continue  # já rejeitado acima; guarda defensiva
        same_session = is_continuous or (
            _session_date(start, market_name) is not None
            and _session_date(start, market_name) == _session_date(end, market_name)
        )
        if not same_session:
            continue
        checked_intervals += 1
        steps = int(round(delta / interval))
        if steps < 1 or abs(delta - steps * interval) > 1.0:
            incidents.append(_base_incident(
                "cadence_mismatch", start, end,
                {"timeframe": timeframe, "delta_seconds": delta, "expected_seconds": interval},
            ))
            continue
        if steps > 1:
            for step in range(1, min(steps, 501)):
                candidate = start + pd.Timedelta(seconds=interval * step)
                if is_continuous or _session_date(candidate, market_name) is not None:
                    missing.append((candidate, end))

    for missing_at, next_at in missing[:500]:
        incidents.append(_base_incident(
            "missing_candle", missing_at, next_at,
            {"timeframe": timeframe, "expected_interval_seconds": interval},
        ))
    if len(missing) > 500:
        incidents.append(_base_incident(
            "missing_candle_overflow", missing[500][0], index[-1],
            {"timeframe": timeframe, "additional_missing_count": len(missing) - 500},
        ))

    assessed_observations = checked_intervals + len(missing)
    coverage_ratio = (checked_intervals / assessed_observations) if assessed_observations else None
    report = {
        "valid": not incidents,
        "market": market_name,
        "timeframe": timeframe,
        "rows": int(len(frame)),
        "last_timestamp": index[-1].isoformat(),
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "expected_interval_seconds": interval,
        "checked_intervals": checked_intervals,
        "missing_candles": len(missing),
        "coverage_ratio": coverage_ratio,
        "incidents": incidents,
        "session_calendar_note": "B3/Forex gaps são avaliados dentro da mesma sessão; feriados/DST não possuem calendário externo.",
    }
    if incidents:
        kinds = sorted({incident["kind"] for incident in incidents})
        raise FeedQualityError(
            f"feed inválido ({market_name}/{timeframe}): {', '.join(kinds)}; última barra={index[-1].isoformat()}",
            incidents,
        )
    return report
