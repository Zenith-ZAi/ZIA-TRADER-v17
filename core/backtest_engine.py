import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List
from datetime import datetime
from core.strategies.manager import StrategyManager
from risk.risk_ai import RiskAI
from config.settings import Settings

logger = logging.getLogger(__name__)

class BacktestEngine:
    """Motor de Backtesting para validar estratégias com dados históricos."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.strategy_manager = StrategyManager(settings)
        self.risk_ai = RiskAI(settings)
        self.results = []
        self.initial_balance = 10000.0
        self.current_balance = self.initial_balance
        self.equity_curve = []

    async def run(self, symbol: str, historical_data: pd.DataFrame, strategy_name: str) -> Dict[str, Any]:
        """Executa o backtest para um símbolo e estratégia específicos."""
        logger.info(f"🚀 Iniciando Backtest: {symbol} | Estratégia: {strategy_name}")
        
        if historical_data.empty:
            logger.error("Dados históricos vazios para backtest.")
            return {"error": "Dados históricos vazios"}

        self.current_balance = self.initial_balance
        self.results = []
        self.equity_curve = [self.initial_balance]

        # Simular o loop de trading sobre os dados históricos
        # Começamos após o período necessário para indicadores (ex: 200 períodos para SMA200)
        start_index = 200 if len(historical_data) > 200 else 0
        
        for i in range(start_index, len(historical_data)):
            current_slice = historical_data.iloc[:i+1]
            current_price = current_slice['close'].iloc[-1]
            
            # 1. Preparar dados para a estratégia
            market_data = self._prepare_market_data(current_slice)
            
            # 2. Obter sinal da estratégia
            strategy_result = self.strategy_manager.select_strategy(strategy_name, market_data)
            
            if strategy_result["signal"] != "hold":
                # 3. Validar com RiskAI (simulado)
                order_data = {
                    "symbol": symbol,
                    "action": strategy_result["signal"],
                    "confidence": strategy_result["confidence"],
                    "price": current_price
                }
                
                # Contexto simplificado para backtest
                market_context = {
                    "historical_data": current_slice,
                    "news_sentiment": 0.5, # Neutro no backtest por padrão
                    "volume_analysis": {"is_confirmed": True},
                    "candle_pattern": "neutral",
                    "atr": (current_slice['high'] - current_slice['low']).mean()
                }
                
                risk_validation = self.risk_ai.validate_order(order_data, self.current_balance, market_context)
                
                if risk_validation["valid"]:
                    # 4. Simular execução
                    self._simulate_execution(risk_validation, historical_data.iloc[i:])
            
            self.equity_curve.append(self.current_balance)

        return self._generate_report(symbol, strategy_name)

    def _prepare_market_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calcula indicadores técnicos para a estratégia."""
        last_price = df['close'].iloc[-1]
        return {
            "price": last_price,
            "volume": df['volume'].iloc[-1],
            "avg_volume": df['volume'].tail(20).mean(),
            "sma_20": df['close'].tail(20).mean(),
            "sma_50": df['close'].tail(50).mean(),
            "sma_200": df['close'].tail(200).mean(),
            "std_dev": df['close'].tail(20).std(),
            "rsi": self._calculate_rsi(df['close']),
            "bid_price": last_price * 0.999,
            "ask_price": last_price * 1.001,
            "min_spread_threshold": 0.005
        }

    def _calculate_rsi(self, series, period=14):
        """Calcula o RSI (Relative Strength Index)."""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs.iloc[-1])) if not np.isnan(rs.iloc[-1]) else 50

    def _simulate_execution(self, risk_validation: Dict[str, Any], future_data: pd.DataFrame):
        """Simula a execução de uma ordem e seu fechamento futuro (SL/TP)."""
        entry_price = risk_validation["price"]
        stop_loss = risk_validation["stop_loss"]
        take_profit = risk_validation["take_profit"]
        action = risk_validation["action"]
        quantity = risk_validation["quantity"]
        
        # Procurar nos dados futuros quando o SL ou TP é atingido
        for _, row in future_data.iterrows():
            high = row['high']
            low = row['low']
            
            if action == "buy":
                if low <= stop_loss:
                    self._record_trade(risk_validation, stop_loss, "SL")
                    break
                elif high >= take_profit:
                    self._record_trade(risk_validation, take_profit, "TP")
                    break
            else: # sell
                if high >= stop_loss:
                    self._record_trade(risk_validation, stop_loss, "SL")
                    break
                elif low <= take_profit:
                    self._record_trade(risk_validation, take_profit, "TP")
                    break

    def _record_trade(self, risk_validation: Dict[str, Any], exit_price: float, exit_reason: str):
        """Registra o resultado de um trade simulado."""
        entry_price = risk_validation["price"]
        quantity = risk_validation["quantity"]
        action = risk_validation["action"]
        
        pnl = (exit_price - entry_price) * quantity
        if action == "sell":
            pnl = -pnl
            
        self.current_balance += pnl
        self.results.append({
            "action": action,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "reason": exit_reason,
            "timestamp": datetime.now().isoformat()
        })

    def _generate_report(self, symbol: str, strategy_name: str) -> Dict[str, Any]:
        """Gera um relatório detalhado do backtest."""
        total_trades = len(self.results)
        winning_trades = sum(1 for t in self.results if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in self.results)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        report = {
            "symbol": symbol,
            "strategy": strategy_name,
            "initial_balance": self.initial_balance,
            "final_balance": self.current_balance,
            "total_pnl": total_pnl,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": self._calculate_profit_factor()
        }
        
        logger.info(f"📊 Relatório Backtest [{symbol}]: PnL Total: {total_pnl:.2f} | Win Rate: {win_rate:.2f}%")
        return report

    def _calculate_profit_factor(self) -> float:
        gross_profit = sum(t["pnl"] for t in self.results if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.results if t["pnl"] < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')
