import asyncio
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime
import numpy as np
from config.settings import settings
from infra.redis_cache import redis_cache
from execution.execution_engine import execution_engine
from utils import logger
from ai.whale_detector import whale_detector

class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""
    def __init__(self):
        self.is_running = False
        self.account_balance = 10000.0 # Saldo inicial simulado para sniper
        self.symbols = settings.SYMBOLS
        self.volatility_threshold = 0.02  # 2% de variação em 1 minuto

    async def start(self):
        """Inicia o motor Sniper."""
        self.is_running = True
        print("Motor Sniper ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Monitoramento de Volatilidade em Tempo Real
                    current_order_flow = self._get_current_order_flow(symbol)
                    historical_data = self._get_historical_data(symbol)
                    current_price = redis_cache.get_price(symbol)
                    previous_price = redis_cache.get_state(f"prev_price_{symbol}")
                    
                    if previous_price:
                        price_change = abs(current_price - previous_price) / previous_price
                        
                        # 2.1. Detecção de Atividade de Baleia
                        whale_activity = whale_detector.detect_whale_activity(historical_data, current_order_flow)
                        if whale_activity["detected"] and whale_activity["magnitude"] > settings.WHALE_ACTIVITY_SNIPER_THRESHOLD:
                            logger.info(f"Sniper: Atividade de Baleia detectada para {symbol}. Magnitude: {whale_activity['magnitude']}")
                            # Ajustar a confiança ou o limiar de entrada/saída com base na baleia
                            # Por exemplo, se a baleia está comprando e o sniper detecta um sinal de compra, aumenta a confiança

                        # 2.2. Detecção de Evento de Volatilidade
                        if price_change > self.volatility_threshold:
                            print(f"Evento Sniper detectado para {symbol}: Variação de {price_change:.2%}")
                            
                            # 3. Execução Rápida (Exemplo: Scalping)
                            action = "buy" if current_price > previous_price else "sell"
                            order_data = {
                                "symbol": symbol,
                                "action": action,
                                "quantity": 0.1,  # Quantidade fixa para o exemplo
                                "price": current_price,
                                "confidence": 0.95  # Alta confiança em eventos de volatilidade
                            }
                            
                            # 4. Execução de Ordem Sniper
                            execution_result = await execution_engine.execute_order(order_data)
                            
                            if execution_result['status'] == "success":
                                print(f"Ordem Sniper executada com sucesso: {execution_result['order_id']}")
                                
                    # 5. Atualiza o preço anterior no cache Redis
                    redis_cache.set_state(f"prev_price_{symbol}", current_price, expire=60)
                    
                await asyncio.sleep(settings.SNIPER_CYCLE_INTERVAL_SECONDS)  # Ciclo rápido configurável
            except Exception as e:
                print(f"Erro no loop do motor Sniper: {e}")
                await asyncio.sleep(5)

    def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        print("Motor Sniper ZIA parado.")

    def _get_historical_data(self, symbol: str) -> pd.DataFrame:
        """Simula a busca de dados históricos para análise do sniper."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=50, freq="1min")
        prices = np.random.uniform(50000, 60000, 50)
        volumes = np.random.uniform(100, 1000, 50)
        return pd.DataFrame({"close": prices, "volume": volumes, "open": prices*0.99, "high": prices*1.01, "low": prices*0.98}, index=dates)

    def _get_current_order_flow(self, symbol: str) -> Dict[str, Any]:
        """Simula o fluxo de ordens atual para detecção de baleias no sniper."""
        return {
            "volume": np.random.uniform(50, 1000),
            "order_size": np.random.uniform(500, 50000),
            "timestamp": datetime.now()
        }

sniper_engine = SniperEngine()
