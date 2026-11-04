"""Read-only market, core-analysis, synchronization, and optimization routes."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.dependencies import get_admin_user, get_app_settings, get_trader_user, get_trading_manager
from core.market_data_collector import MarketDataCollectionError, ProviderCollectionError

logger = logging.getLogger(__name__)
router = APIRouter()


class MarketDataCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: Literal["crypto", "equity", "forex"]
    symbols: list[str] = Field(min_length=1, max_length=10)
    providers: list[Literal["binance_public", "alpha_vantage", "coingecko", "yahoo_chart"]] = Field(
        min_length=1, max_length=3
    )
    timeframe: str = Field(default="1d", pattern="^(1m|5m|15m|30m|1h|4h|1d)$")
    limit: int = Field(default=100, ge=1, le=1000)
    dry_run: bool = True

    @field_validator("symbols")
    @classmethod
    def symbols_must_be_nonblank(cls, value: list[str]) -> list[str]:
        normalized = [symbol.strip() for symbol in value]
        if any(not symbol for symbol in normalized):
            raise ValueError("symbols cannot contain blank values")
        return normalized


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


@router.post("/market-data/collect")
async def collect_market_data(
    request: MarketDataCollectionRequest,
    current_user: dict[str, Any] = Depends(get_admin_user),
    manager: Any = Depends(get_trading_manager),
    settings: Any = Depends(get_app_settings),
) -> dict[str, Any]:
    """Collect licensed/read-only OHLCV sources; never updates the live trading feed."""
    if not settings.MARKET_DATA_INGESTION_ENABLED:
        raise HTTPException(status_code=503, detail={"code": "market_data_ingestion_disabled"})
    try:
        return await manager.command_manager.collect_market_data(**request.model_dump())
    except MarketDataCollectionError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    except ProviderCollectionError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code}) from exc
    except Exception as exc:
        # Do not log arbitrary provider exceptions: query URLs can contain API keys.
        logger.error("Market-data collection failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="coleta indisponível no momento") from exc


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
