"""Backtest determinístico compartilhando a mesma leitura de mercado do motor."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config.settings import Settings
from core.market_signals import calculate_market_signal

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Simula ordens em OHLCV histórico sem usar dados futuros."""

    def __init__(self, settings: Settings, db_manager):
        self.settings = settings
        self.db_manager = db_manager
        logger.info("BacktestEngine inicializado.")

    @staticmethod
    def _price(row: pd.Series, preferred: str, fallback: str = "close") -> float:
        value = row.get(preferred, row.get(fallback, np.nan))
        return float(value) if pd.notna(value) else float("nan")

    def _close_trade(
        self,
        trade: Dict[str, Any],
        exit_price: float,
        exit_index: Any,
        reason: str,
        fee_rate: float,
    ) -> Dict[str, Any]:
        direction = 1.0 if trade["action"] == "buy" else -1.0
        gross_pnl = (exit_price - trade["entry_price"]) * trade["quantity"] * direction
        exit_fee = exit_price * trade["quantity"] * fee_rate
        net_pnl = gross_pnl - trade["entry_fee"] - exit_fee
        return {
            **trade,
            "exit_price": float(exit_price),
            "exit_index": str(exit_index),
            "gross_pnl": float(gross_pnl),
            "fees": float(trade["entry_fee"] + exit_fee),
            "pnl": float(net_pnl),
            "return_pct": float(net_pnl / max(trade["entry_price"] * trade["quantity"], 1e-9)),
            "exit_reason": reason,
        }

    async def run(
        self,
        symbol: str,
        historical_data: Any,
        strategy_name: str = "IA Adaptativa",
    ) -> Dict[str, Any]:
        """Executa um backtest walk-forward com capital e risco configuráveis."""
        if not isinstance(historical_data, pd.DataFrame) or historical_data.empty:
            return {
                "symbol": symbol,
                "strategy": strategy_name,
                "status": "invalid_data",
                "reason": "histórico vazio ou inválido",
                "trades_executed": 0,
            }

        data = historical_data.copy().sort_index()
        required = {"close"}
        if not required.issubset(data.columns):
            return {
                "symbol": symbol,
                "strategy": strategy_name,
                "status": "invalid_data",
                "reason": "coluna close ausente",
                "trades_executed": 0,
            }
        data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])
        if len(data) < 40:
            return {
                "symbol": symbol,
                "strategy": strategy_name,
                "status": "insufficient_data",
                "reason": "são necessárias pelo menos 40 barras",
                "trades_executed": 0,
            }

        initial_capital = float(self.settings.BACKTEST_INITIAL_CAPITAL)
        capital = initial_capital
        fee_rate = float(self.settings.BACKTEST_FEE_RATE)
        stop_loss_pct = float(self.settings.BACKTEST_STOP_LOSS_PCT)
        take_profit_pct = float(self.settings.BACKTEST_TAKE_PROFIT_PCT)
        risk_per_trade = float(self.settings.MAX_RISK_PER_TRADE)
        max_exposure = float(self.settings.MAX_EXPOSURE_PER_SYMBOL)
        position: Optional[Dict[str, Any]] = None
        trades: List[Dict[str, Any]] = []
        equity_curve: List[float] = [capital]
        quality_counts = {"good": 0, "rejected": 0, "bad_data": 0}

        for index in range(35, len(data)):
            row = data.iloc[index]
            price = self._price(row, "open")
            if not np.isfinite(price) or price <= 0:
                price = self._price(row, "close")
            if not np.isfinite(price) or price <= 0:
                quality_counts["bad_data"] += 1
                equity_curve.append(capital)
                continue

            window = data.iloc[:index]
            signal = calculate_market_signal(
                window,
                min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
            )
            quality_counts[signal.status] = quality_counts.get(signal.status, 0) + 1

            high = self._price(row, "high")
            low = self._price(row, "low")
            if position is not None:
                stop_hit = (
                    low <= position["stop_loss"] if position["action"] == "buy"
                    else high >= position["stop_loss"]
                )
                take_hit = (
                    high >= position["take_profit"] if position["action"] == "buy"
                    else low <= position["take_profit"]
                )
                if stop_hit or take_hit:
                    exit_price = position["stop_loss"] if stop_hit else position["take_profit"]
                    closed = self._close_trade(position, exit_price, data.index[index], "stop_loss" if stop_hit else "take_profit", fee_rate)
                    capital += closed["pnl"]
                    trades.append(closed)
                    position = None

            if position is not None and signal.action in {"buy", "sell"} and signal.action != position["action"]:
                closed = self._close_trade(position, price, data.index[index], "signal_flip", fee_rate)
                capital += closed["pnl"]
                trades.append(closed)
                position = None

            if position is None and signal.action in {"buy", "sell"}:
                risk_amount = capital * risk_per_trade
                unit_risk = max(price * stop_loss_pct, 1e-9)
                quantity = risk_amount / unit_risk
                quantity = min(quantity, (capital * max_exposure) / price)
                if quantity > 0:
                    entry_fee = price * quantity * fee_rate
                    position = {
                        "action": signal.action,
                        "entry_price": price,
                        "entry_index": str(data.index[index]),
                        "quantity": float(quantity),
                        "entry_fee": float(entry_fee),
                        "stop_loss": price * (1 - stop_loss_pct) if signal.action == "buy" else price * (1 + stop_loss_pct),
                        "take_profit": price * (1 + take_profit_pct) if signal.action == "buy" else price * (1 - take_profit_pct),
                        "signal_confidence": float(signal.confidence),
                        "signal_score": float(signal.score),
                    }

            mark_price = self._price(row, "close")
            unrealized = 0.0
            if position is not None and np.isfinite(mark_price):
                direction = 1.0 if position["action"] == "buy" else -1.0
                unrealized = (mark_price - position["entry_price"]) * position["quantity"] * direction
            equity_curve.append(capital + unrealized)

        if position is not None:
            final_price = self._price(data.iloc[-1], "close")
            closed = self._close_trade(position, final_price, data.index[-1], "end_of_data", fee_rate)
            capital += closed["pnl"]
            trades.append(closed)
            equity_curve[-1] = capital

        equity = np.asarray(equity_curve, dtype=float)
        returns = pd.Series(equity).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        downside = returns.std(ddof=1) if len(returns) > 1 else 0.0
        sharpe = float((returns.mean() / downside) * np.sqrt(252)) if downside > 0 else 0.0
        running_max = np.maximum.accumulate(equity)
        drawdowns = (equity - running_max) / np.maximum(running_max, 1e-9)
        max_drawdown = float(drawdowns.min()) if len(drawdowns) else 0.0
        wins = [trade for trade in trades if trade["pnl"] > 0]
        losses = [trade for trade in trades if trade["pnl"] < 0]
        gross_profit = sum(trade["pnl"] for trade in wins)
        gross_loss = abs(sum(trade["pnl"] for trade in losses))

        result = {
            "symbol": symbol,
            "strategy": strategy_name,
            "status": "ok",
            "start_date": data.index.min().isoformat(),
            "end_date": data.index.max().isoformat(),
            "initial_capital": initial_capital,
            "final_capital": float(capital),
            "total_pnl": float(capital - initial_capital),
            "return_pct": float((capital / initial_capital) - 1.0),
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "trades_executed": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
            "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
            "signal_quality": quality_counts,
            "trades": trades,
        }
        logger.info("Backtest para %s concluído: PNL=%.2f, trades=%s", symbol, result["total_pnl"], len(trades))
        return result
