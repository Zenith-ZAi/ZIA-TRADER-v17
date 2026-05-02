import asyncio
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any
from datetime import datetime

from config.settings import Settings
from infra.redis_cache import RedisCache
from execution.execution_engine import ExecutionEngine
from ai.whale_detector import WhaleDetector
from execution.exchange_connector import ExchangeConnector

logger = logging.getLogger(__name__)

class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""
    def __init__(self, settings: Settings, exchange_connector: ExchangeConnector, execution_engine: ExecutionEngine, whale_detector: WhaleDetector, redis_cache: RedisCache):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.execution_engine = execution_engine
        self.whale_detector = whale_detector
        self.redis_cache = redis_cache
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
                        
                        # 2.1. Detecção de Atividade de Baleia
                        # Para o WhaleDetector, precisamos de um fluxo de ordens mais detalhado
                        # Isso exigiria uma integração de websocket ou API de Level 2/3, aqui simulamos com dados de mercado
                        current_order_flow = {
                            "symbol": symbol,
                            "total_volume": current_market_data.get("volume", 0),
                            "buys": [], # Em um cenário real, preencheríamos com ordens de compra recentes
                            "sells": [] # Em um cenário real, preencheríamos com ordens de venda recentes
                        }
                        whale_activity = self.whale_detector.detect_whale_activity(historical_data, current_order_flow)
                        if whale_activity["detected"] and whale_activity["magnitude"] > self.settings.WHALE_ACTIVITY_SNIPER_THRESHOLD:
                            logger.info(f"Sniper: Atividade de Baleia detectada para {symbol}. Magnitude: {whale_activity["magnitude"]}")
                            # Ajustar a confiança ou o limiar de entrada/saída com base na baleia
                            # Por exemplo, se a baleia está comprando e o sniper detecta um sinal de compra, aumenta a confiança

                        # 2.2. Detecção de Evento de Volatilidade
                        if price_change > self.volatility_threshold:
                            logger.info(f"Sniper: Evento de alta volatilidade detectado para {symbol}: Variação de {price_change:.2%}")
                            
                            # 3. Execução Rápida (Exemplo: Scalping)
                            action = "buy" if current_price > float(previous_price) else "sell"
                            order_data = {
                                "symbol": symbol,
                                "action": action,
                                "quantity": self.settings.SNIPER_TRADE_QUANTITY,  # Quantidade configurável
                                "price": current_price,
                                "confidence": 0.95  # Alta confiança em eventos de volatilidade
                            }
                            
                            # 4. Execução de Ordem Sniper
                            # A validação de risco para sniper pode ser mais leve ou pré-aprovada
                            # Aqui, passamos diretamente para a execução, assumindo que a estratégia sniper já validou o risco
                            execution_result = await self.execution_engine.execute_order(order_data)
                            
                            if execution_result["status"] == "success":
                                logger.info(f"Sniper: Ordem executada com sucesso: {execution_result["order_id"]}")
                                
                    # 5. Atualiza o preço anterior no cache Redis
                    await self.redis_cache.set_state(previous_price_key, str(current_price), expire=self.settings.SNIPER_PRICE_CACHE_EXPIRE)
                    
                await asyncio.sleep(self.settings.SNIPER_CYCLE_INTERVAL_SECONDS)  # Ciclo rápido configurável
            except Exception as e:
                logger.error(f"Erro no loop do motor Sniper: {e}")
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        logger.info("Motor Sniper ZIA parado.")
