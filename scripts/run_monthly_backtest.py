"""Executa backtesting mensal multiativo com persistência auditável.

O script usa somente o endpoint público de OHLCV, grava datasets com hash,
persiste cada resultado no banco e nunca envia ordens, treina/promove modelo ou
altera flags de trading. É destinado ao VPS em modo histórico/shadow.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings, settings as default_settings
from core.backtest_engine import BacktestEngine
from core.dataset_integrity import validate_ohlcv
from database_manager import DatabaseManager
from scripts.fetch_binance_ohlcv import INTERVAL_MS, fetch_async


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _dataset_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"])
    frame = frame.rename(columns={"open_time": "timestamp"}).set_index("timestamp").sort_index()
    numeric = ["open", "high", "low", "close", "volume"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    return frame[numeric].dropna()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_settings() -> Settings:
    """Copia o ambiente, mas força o runner a permanecer histórico/simulado."""
    return default_settings.model_copy(
        update={
            "BINANCE_MODE": "simulated",
            "LIVE_TRADING_ENABLED": False,
            "LIVE_MODE": False,
            "LIVE_KILL_SWITCH": True,
            "AUTONOMOUS_TRADING_ENABLED": False,
            "MANUAL_TRADING_ENABLED": False,
            "AUTO_START_ENGINES": False,
            "SHADOW_MODE_ENABLED": True,
            "FRICTION_ENABLED": True,
            "FRICTION_SLEEP_ENABLED": False,
        },
        deep=True,
    )


async def run_monthly_backtest(
    symbols: list[str],
    interval: str,
    days: int,
    data_dir: Path,
    database_url: str,
    output_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"intervalo não suportado: {interval}")
    if days <= 0:
        raise ValueError("days deve ser positivo")

    data_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db_manager = DatabaseManager(database_url)
    db_manager.create_tables()
    run_settings = _safe_settings()
    engine = BacktestEngine(run_settings, db_manager)
    interval_bars = max(1, (86_400_000 // INTERVAL_MS[interval]) * days)
    start = _parse_datetime(start_date)
    end = _parse_datetime(end_date)
    start_ms = int(start.timestamp() * 1000) if start else None
    end_ms = int(end.timestamp() * 1000) if end else None
    if end_ms is not None and start_ms is not None and end_ms <= start_ms:
        raise ValueError("end-date deve ser posterior a start-date")

    result: dict[str, Any] = {
        "protocol": "monthly_backtest",
        "mode": "historical_shadow",
        "orders_sent": 0,
        "live_trading_enabled": False,
        "model_promoted": False,
        "interval": interval,
        "days_requested": days,
        "database_url_redacted": database_url.split("@")[-1],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
        "errors": {},
    }

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        dataset_path = data_dir / f"{symbol.lower()}_{interval}.csv"
        try:
            frame_raw = await fetch_async(
                symbol,
                interval,
                interval_bars,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            )
            frame_raw.to_csv(dataset_path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ")
            frame = _dataset_frame(dataset_path)
            integrity = validate_ohlcv(frame, timeframe=interval, require_closed=True, reject_gaps=False, min_coverage=0.95)
            if len(frame) < 40:
                raise RuntimeError(f"dataset insuficiente após remover candles abertos: {len(frame)} barras")
            backtest = await engine.run(symbol.replace("USDT", "/USDT"), frame, "VPS Monthly Historical")
            run_id = f"monthly-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{symbol.lower()}"
            persisted = db_manager.create_backtest_run(
                run_id=run_id,
                symbol=symbol,
                timeframe=interval,
                dataset_path=str(dataset_path),
                dataset_sha256=_sha256(dataset_path),
                result=backtest,
                configuration={
                    "days": days,
                    "interval": interval,
                    "friction_enabled": True,
                    "orders_sent": 0,
                    "live_trading_enabled": False,
                    "model_promoted": False,
                },
            )
            result["runs"].append({
                "run_id": run_id,
                "symbol": symbol,
                "dataset": {
                    "path": str(dataset_path),
                    "rows": len(frame),
                    "sha256": _sha256(dataset_path),
                    "integrity": integrity,
                    "start": frame.index.min().isoformat(),
                    "end": frame.index.max().isoformat(),
                },
                "backtest": {
                    "status": backtest.get("status"),
                    "total_pnl": backtest.get("total_pnl"),
                    "return_pct": backtest.get("return_pct"),
                    "sharpe_ratio": backtest.get("sharpe_ratio"),
                    "maximum_drawdown": backtest.get("maximum_drawdown"),
                    "trades_executed": backtest.get("trades_executed", 0),
                },
                "persisted": persisted,
            })
        except Exception as exc:  # noqa: BLE001 - continua os demais ativos e registra a falha
            result["errors"][symbol] = str(exc)

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtesting mensal histórico/shadow sem ordens")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--data-dir", default="data/monthly_backtest")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db"))
    parser.add_argument("--output", default="data/monthly_backtest_result.json")
    parser.add_argument("--start-date", default=None, help="ISO-8601 UTC opcional")
    parser.add_argument("--end-date", default=None, help="ISO-8601 UTC opcional")
    args = parser.parse_args()
    symbols = [value for value in args.symbols.split(",") if value.strip()]
    result = asyncio.run(
        run_monthly_backtest(
            symbols=symbols,
            interval=args.interval,
            days=args.days,
            data_dir=Path(args.data_dir),
            database_url=args.database_url,
            output_path=Path(args.output),
            start_date=args.start_date,
            end_date=args.end_date,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
