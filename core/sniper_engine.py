import asyncio
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any
from database import MarketType, OrderStatus
from datetime import datetime

from config.settings import Settings
from infra.redis_cache import RedisCache
from execution.execution_engine import ExecutionEngine
from ai.whale_detector import WhaleDetector
from core.market_signals import calculate_market_signal
from execution.exchange_connector import ExchangeConnector
from risk.risk_ai import RiskAI

logger = logging.getLogger(__name__)

class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""
    def __init__(self, settings: Settings, exchange_connector: ExchangeConnector, execution_engine: ExecutionEngine, whale_detector: WhaleDetector, redis_cache: RedisCache, db_manager):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.execution_engine = execution_engine
        self.whale_detector = whale_detector
        self.redis_cache = redis_cache
        self.db_manager = db_manager
        self.account_id = "default_account" # Pode ser dinâmico em um sistema real
        self.risk_ai = RiskAI(settings, db_manager)
        self.is_running = False
        self.symbols = self.settings.SYMBOLS
        self.volatility_threshold = self.settings.SNIPER_VOLATILITY_THRESHOLD  # Ex: 2% de variação em 1 minuto

    async def start(self):
        """Inicia o motor Sniper."""
        self.is_running = True
        logger.info("Motor Sniper ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Monitoramento de Volatilidade em Tempo Real
                    current_market_data = await self.exchange_connector.get_market_data(symbol)
                    historical_data = await self.exchange_connector.get_historical_data(symbol, self.settings.SNIPER_TIMEFRAME)
                    current_price = current_market_data.get("last") if current_market_data else None
                    
                    if current_price is None:
                        logger.warning(f"[{symbol}] Sniper: Não foi possível obter o preço atual. Pulando ciclo.")
                        continue

                    previous_price_key = f"prev_price_sniper_{symbol}"
                    previous_price = await self.redis_cache.get_state(previous_price_key)
                    
                    if previous_price:
                        price_change = abs(current_price - float(previous_price)) / float(previous_price)
                        
                        # 2.1. Detecção de atividade concentrada no livro de ordens
                        order_book = await self.exchange_connector.get_order_book(symbol, limit=20)
                        current_order_flow = {
                            "symbol": symbol,
                            "total_volume": current_market_data.get("volume", 0),
                            "buys": order_book.get("bids", []),
                            "sells": order_book.get("asks", []),
                            "last_update_id": order_book.get("last_update_id"),
                        }
                        whale_activity = self.whale_detector.detect_whale_activity(historical_data, current_order_flow)
                        whale_detected = bool(
                            whale_activity.get("detected")
                            and whale_activity.get("magnitude", 0.0) >= self.settings.WHALE_ACTIVITY_SNIPER_THRESHOLD
                        )
                        if whale_detected:
                            logger.info("Sniper: baleia detectada para %s; magnitude=%.3f", symbol, whale_activity["magnitude"])

                        # 2.2. Volatilidade só vira entrada quando há confluência real.
                        if price_change > self.volatility_threshold:
                            action = "buy" if current_price > float(previous_price) else "sell"
                            market_signal = calculate_market_signal(
                                historical_data,
                                min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                                max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                            )
                            whale_direction_matches = (
                                (action == "buy" and whale_activity.get("sentiment") == "bullish")
                                or (action == "sell" and whale_activity.get("sentiment") == "bearish")
                            )
                            confirmed_event = bool(
                                self.settings.AUTONOMOUS_TRADING_ENABLED
                                and whale_detected
                                and whale_direction_matches
                                and market_signal.action == action
                                and market_signal.confidence >= float(self.settings.MIN_CONFIDENCE_THRESHOLD)
                            )
                            logger.info(
                                "Sniper: evento=%s ação=%s sinal=%s confiança=%.2f confirmado=%s",
                                symbol,
                                action,
                                market_signal.action,
                                market_signal.confidence,
                                confirmed_event,
                            )
                            if confirmed_event:
                                order_data = {
                                    "symbol": symbol,
                                    "action": action,
                                    "quantity": self.settings.SNIPER_TRADE_QUANTITY,
                                    "price": current_price,
                                    "confidence": min(float(market_signal.confidence), float(whale_activity.get("confidence", 0.0))),
                                }
                                account_state = self.db_manager.get_account_state(self.account_id)
                                try:
                                    exchange_balances = await self.exchange_connector.get_account_balance()
                                except Exception as exc:
                                    logger.warning("Sniper: saldo privado indisponível para %s: %s", symbol, exc)
                                    exchange_balances = {}
                                account_balance = self.risk_ai.quote_equivalent_balance(exchange_balances, symbol, current_price) or (account_state.balance if account_state else 0.0)
                                risk_context = {
                                    "historical_data": historical_data,
                                    "exchange_balances": exchange_balances,
                                    "market_signal": market_signal.to_dict(),
                                    "whale_activity": whale_activity,
                                    "current_order_flow": current_order_flow,
                                }
                                risk_validation = self.risk_ai.validate_order(
                                    order_data,
                                    account_balance,
                                    risk_context,
                                )
                                if not risk_validation["valid"]:
                                    logger.warning("Sniper: ordem rejeitada por risco para %s: %s", symbol, risk_validation["reason"])
                                else:
                                    execution_order = {**order_data, **risk_validation}
                                    execution_result = await self.execution_engine.execute_order(execution_order)
                                    if execution_result["status"] == "success":
                                        logger.info("Sniper: Ordem executada com sucesso: %s", execution_result["order_id"])
                                        self.db_manager.create_execution_history(
                                            account_id=self.account_id,
                                            execution_id=execution_result["order_id"],
                                            order_id=execution_result["order_id"],
                                            symbol=order_data["symbol"],
                                            market_type=MarketType.CRYPTO,
                                            action=order_data["action"],
                                            filled_price=execution_result["filled_price"],
                                            filled_quantity=execution_result["filled_quantity"],
                                            commission=execution_result.get("commission", 0.0),
                                        )
                                
                    # 5. Atualiza o preço anterior no cache Redis
                    await self.redis_cache.set_state(previous_price_key, str(current_price), expire=self.settings.SNIPER_PRICE_CACHE_EXPIRE)
                    
                await asyncio.sleep(self.settings.SNIPER_CYCLE_INTERVAL_SECONDS)  # Ciclo rápido configurável
            except Exception as e:
                logger.error(f"Erro no loop do motor Sniper: {e}")
                self.db_manager.create_system_log("ERROR", f"Erro no loop do motor Sniper: {e}", "SniperEngine")
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    async def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        logger.info("Motor Sniper ZIA parado.")
