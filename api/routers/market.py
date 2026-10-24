"""Read-only market, core-analysis, synchronization, and optimization routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import get_app_settings, get_trader_user, get_trading_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/market")
async def market_alias(
    symbol: str,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    try:
        normalized = manager.market_connector.normalize_symbol(symbol)
        market_data = await manager.market_connector.get_market_data(normalized)
        order_book = await manager.market_connector.get_order_book(normalized, limit=20)
        return {"symbol": normalized, "market": market_data, "order_book": order_book}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dados de mercado indisponíveis") from exc


@router.get("/core/analyze")
async def analyze_core_symbol(
    symbol: str,
    offline: bool = False,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    """Run explainable market analysis; this endpoint does not submit orders."""
    try:
        return await manager.command_manager.analyze_symbol(symbol, offline=offline)
    except Exception as exc:
        logger.warning("Falha na análise do core para %s: %s", symbol, exc)
        raise HTTPException(status_code=503, detail="análise indisponível no momento") from exc


@router.post("/core/sync")
async def sync_core_data(
    request: dict[str, Any] = Body(default_factory=dict),
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
    settings: Any = Depends(get_app_settings),
) -> dict[str, Any]:
    """Synchronize feeds and return snapshots without executing orders."""
    raw_symbols = request.get("symbols") or settings.SYMBOLS
    symbols = [raw_symbols] if isinstance(raw_symbols, str) else raw_symbols
    try:
        return await manager.command_manager.sync_market(
            symbols=symbols,
            limit=int(request.get("limit", 250)),
            offline=bool(request.get("offline", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Falha na sincronização do core: %s", exc)
        raise HTTPException(status_code=503, detail="sincronização indisponível no momento") from exc


@router.get("/api/optimize_sharpe")
async def optimize_sharpe(
    asset_list: str,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
    settings: Any = Depends(get_app_settings),
) -> dict[str, Any]:
    requested_assets = [value.strip() for value in asset_list.split(",") if value.strip()]
    if not requested_assets:
        raise HTTPException(status_code=400, detail="asset_list não pode ser vazio")
    symbol = requested_assets[0]
    try:
        historical_data = await manager.exchange_connector.get_historical_data(
            symbol,
            settings.TIMEFRAME,
            limit=min(8760, 10000),
        )
        # Keep ML/optimization imports off API import/startup paths.
        from risk.strategy_optimizer import OptimizationBudget, StrategyOptimizer

        optimizer = StrategyOptimizer(
            settings,
            manager.backtest_engine.db_manager,
            budget=OptimizationBudget(
                max_evaluations=settings.OPTIMIZER_MAX_EVALUATIONS,
                max_seconds=settings.OPTIMIZER_MAX_SECONDS,
                validation_fraction=settings.OPTIMIZER_VALIDATION_FRACTION,
                min_trades=settings.OPTIMIZER_MIN_TRADES,
            ),
        )
        recommendation = await optimizer.optimize_async(
            symbol,
            historical_data,
            strategy_name="API Sharpe Optimization",
        )
        return {
            "requested_assets": requested_assets,
            "optimized_asset": symbol,
            "orders_sent": 0,
            "recommendation": recommendation,
        }
    except Exception as exc:
        logger.exception("Falha na otimização Sharpe para %s", symbol)
        raise HTTPException(status_code=503, detail="otimização indisponível no momento") from exc
