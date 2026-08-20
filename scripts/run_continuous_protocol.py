"""Executa o protocolo de otimização contínua somente em dados históricos/shadow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from core.backtest_engine import BacktestEngine
from risk.correlation_manager import CorrelationManager
from risk.sharpe_analyzer import SharpeAnalyzer
from risk.strategy_optimizer import OptimizationBudget, StrategyOptimizer
from scripts.fetch_binance_ohlcv import fetch


DEFAULT_ASSETS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "AVAXUSDT",
]


def load_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["open_time"])
    frame = frame.rename(columns={"open_time": "timestamp"}).set_index("timestamp").sort_index()
    columns = ["open", "high", "low", "close", "volume"]
    frame[columns] = frame[columns].apply(pd.to_numeric, errors="raise")
    return frame[columns].replace([np.inf, -np.inf], np.nan).dropna()


def make_settings(events_file: str | None = None) -> Settings:
    values = {
        "PULLBACK_STRATEGY_ENABLED": True,
        "FRICTION_ENABLED": True,
        "FRICTION_SLEEP_ENABLED": False,
        "FRICTION_MIN_SLIPPAGE_TICKS": 0.5,
        "FRICTION_MAX_SLIPPAGE_TICKS": 2.0,
        "FRICTION_COMMISSION_RATE": 0.0005,
        "BACKTEST_FEE_RATE": 0.001,
        "BACKTEST_INITIAL_CAPITAL": 10_000.0,
        "MAX_RISK_PER_TRADE": 0.02,
        "MAX_EXPOSURE_PER_SYMBOL": 0.10,
        "METRICS_PERIODS_PER_YEAR": 8760,
        "OPTIMIZER_MAX_EVALUATIONS": 8,
        "OPTIMIZER_MAX_SECONDS": 540,
        "OPTIMIZER_VALIDATION_FRACTION": 0.30,
        "OPTIMIZER_MIN_TRADES": 3,
    }
    if events_file:
        values["ECONOMIC_EVENTS_FILE"] = events_file
    return Settings(**values)


def latest_window(frame: pd.DataFrame, bars: int = 8760) -> pd.DataFrame:
    return frame.tail(min(int(bars), len(frame))).copy()


def result_summary(result: dict) -> dict:
    return {
        key: result.get(key)
        for key in [
            "status", "total_pnl", "return_pct", "sharpe_ratio", "sortino_ratio",
            "calmar_ratio", "max_drawdown", "trades_executed", "win_rate", "total_fees",
        ]
    }


def monte_carlo_sharpe(returns: pd.Series, periods_per_year: int, horizon_periods: int, simulations: int = 1000, seed: int = 42) -> dict:
    values = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if values.size < 2:
        return {"status": "insufficient_data", "simulations": 0}
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(int(simulations), int(horizon_periods)), replace=True)
    means = samples.mean(axis=1)
    deviations = samples.std(axis=1, ddof=1)
    sharpes = np.divide(means, deviations, out=np.zeros_like(means), where=deviations > 0) * np.sqrt(periods_per_year)
    return {
        "status": "scenario_estimate",
        "simulations": int(simulations),
        "horizon_periods": int(horizon_periods),
        "seed": int(seed),
        "mean_sharpe": float(np.mean(sharpes)),
        "p05_sharpe": float(np.quantile(sharpes, 0.05)),
        "p50_sharpe": float(np.quantile(sharpes, 0.50)),
        "p95_sharpe": float(np.quantile(sharpes, 0.95)),
        "warning": "bootstrap histórico; não é previsão garantida nem sinal de entrada",
    }


def fetch_assets(symbols: list[str], interval: str, limit: int, output_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            frame = fetch(symbol, interval, limit)
            path = output_dir / f"{symbol.lower()}_{interval}.csv"
            frame.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ")
            datasets[symbol] = frame.rename(columns={"open_time": "timestamp"}).set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        except Exception as exc:
            errors[symbol] = str(exc)
    return datasets, errors


async def run_protocol(dataset_path: Path, symbols: list[str], asset_limit: int, assets_dir: Path, events_file: str | None = None) -> dict:
    started = time.perf_counter()
    base_frame = load_ohlcv(dataset_path)
    settings = make_settings(events_file)
    one_year = latest_window(base_frame)
    optimizer = StrategyOptimizer(
        settings,
        budget=OptimizationBudget(
            max_evaluations=settings.OPTIMIZER_MAX_EVALUATIONS,
            max_seconds=settings.OPTIMIZER_MAX_SECONDS,
            validation_fraction=settings.OPTIMIZER_VALIDATION_FRACTION,
            min_trades=settings.OPTIMIZER_MIN_TRADES,
        ),
    )
    optimization = await optimizer.optimize_async(
        "BTC/USDT",
        one_year,
        data_window_bars=len(one_year),
        strategy_name="PromptContínuo Sharpe Search",
    )
    baseline = optimization.get("baseline", {})
    top = optimization.get("top10", [])
    best_params = top[0].get("params", {}) if top else {}
    optimized_settings = settings.model_copy(update=best_params, deep=True)

    year_results = {}
    for year in (2020, 2022):
        year_frame = base_frame[base_frame.index.year == year]
        if len(year_frame) >= 100:
            current = await BacktestEngine(settings, None).run("BTC/USDT", year_frame, f"baseline_{year}")
            optimized = await BacktestEngine(optimized_settings, None).run("BTC/USDT", year_frame, f"optimized_{year}")
            year_results[str(year)] = {"baseline": result_summary(current), "optimized": result_summary(optimized)}
        else:
            year_results[str(year)] = {"status": "insufficient_data", "rows": len(year_frame)}

    requested_assets = [symbol.upper() for symbol in symbols[: max(1, int(asset_limit))]]
    asset_data, fetch_errors = fetch_assets(requested_assets, "1h", 8760, assets_dir)
    price_data = {symbol: frame["close"] for symbol, frame in asset_data.items()}
    correlation = CorrelationManager(
        low_correlation_threshold=settings.PORTFOLIO_LOW_CORRELATION_THRESHOLD,
        max_weight=settings.PORTFOLIO_MAX_WEIGHT,
    ).recommend(price_data, risk_free_rate=settings.RISK_FREE_RATE_ANNUAL / settings.METRICS_PERIODS_PER_YEAR)
    weights = correlation.get("weights", {})
    returns_frame = CorrelationManager.returns_frame(price_data)
    portfolio_returns = returns_frame[list(weights)].mul(pd.Series(weights)).sum(axis=1) if weights else pd.Series(dtype=float)
    portfolio_metrics = SharpeAnalyzer(
        risk_free_rate=settings.RISK_FREE_RATE_ANNUAL,
        periods_per_year=settings.METRICS_PERIODS_PER_YEAR,
    ).analyze(portfolio_returns.tolist())
    correlation["portfolio_metrics"] = portfolio_metrics
    correlation["monte_carlo_3m"] = monte_carlo_sharpe(
        portfolio_returns,
        settings.METRICS_PERIODS_PER_YEAR,
        horizon_periods=90 * 24,
        simulations=1000,
    )
    avg_corr = returns_frame.corr().mean() if not returns_frame.empty else pd.Series(dtype=float)
    correlation["assets_to_avoid"] = [asset for asset, value in avg_corr.items() if abs(float(value)) >= 0.80]

    # Candle-only history has no historical bid/ask/order-book snapshots; no false cost reduction is claimed.
    cost_test = {
        "status": "not_tested",
        "reason": "OHLCV público não contém spread e profundidade históricos; comparar slippage real exigiria snapshots de book, não inventados.",
    }
    return {
        "protocol": "PromptContínuo",
        "mode": "historical_shadow",
        "orders_sent": 0,
        "dataset": {
            "path": str(dataset_path),
            "rows": len(base_frame),
            "available_start": base_frame.index.min().isoformat(),
            "available_end": base_frame.index.max().isoformat(),
            "optimization_window_rows": len(one_year),
            "optimization_window_start": one_year.index.min().isoformat(),
            "optimization_window_end": one_year.index.max().isoformat(),
        },
        "tests": {
            "A_optimization_12m": {
                "baseline_validation": baseline.get("validation", {}),
                "top5": top[:5],
                "best_params": best_params,
                "eligible_evaluations": optimization.get("eligible_evaluations", 0),
                "selection_warning": optimization.get("selection_warning"),
                "timed_out": optimization.get("timed_out", False),
                "elapsed_seconds": optimization.get("elapsed_seconds"),
            },
            "B_high_volatility": year_results,
            "C_cost_reduction": cost_test,
            "D_correlation_diversification": {
                "requested_assets": requested_assets,
                "available_assets": list(asset_data),
                "fetch_errors": fetch_errors,
                "recommendation": correlation,
            },
        },
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "A janela de 12 meses usa o trecho mais recente disponível no dataset local, que termina em 2024-12-31.",
            "A projeção Monte Carlo é bootstrap histórico e não representa previsão certa.",
            "O Teste C não afirma redução de custo sem histórico de order book.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/dataset_btcusdt_1h_2020_2024.csv")
    parser.add_argument("--assets", default=",".join(DEFAULT_ASSETS))
    parser.add_argument("--asset-limit", type=int, default=10)
    parser.add_argument("--assets-dir", default="data/continuous_assets")
    parser.add_argument("--output", default="data/continuous_protocol_result.json")
    parser.add_argument("--events-file", default=None)
    args = parser.parse_args()
    symbols = [value.strip() for value in args.assets.split(",") if value.strip()]
    result = asyncio.run(run_protocol(Path(args.dataset), symbols, args.asset_limit, Path(args.assets_dir), args.events_file))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
