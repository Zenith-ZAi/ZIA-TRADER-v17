import asyncio
import pandas as pd
from typing import List, Dict, Any
from config.settings import settings
from infra.redis_cache import redis_cache
from ai.transformer_model import transformer_model
from risk.risk_ai import risk_ai
from execution.execution_engine import execution_engine

class TradingEngine:
    """Motor de trading principal que coordena a análise e execução."""
    def __init__(self):
        self.is_running = False
        self.symbols = settings.SYMBOLS
        self.timeframe = settings.TIMEFRAME
        self.account_balance = 10000.0  # Saldo inicial simulado

    async def start(self):
        """Inicia o motor de trading."""
        self.is_running = True
        print("Motor de Trading ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Busca dados históricos e atuais
                    # Em produção, buscaríamos do banco de dados ou API
                    historical_data = self._get_historical_data(symbol)
                    current_price = redis_cache.get_price(symbol)
                    
                    # 2. Análise de IA (Transformer)
                    analysis = transformer_model.predict(historical_data)
                    
                    # 3. Gerenciamento de Risco
                    if analysis['prediction'] != "hold":
                        order_data = {
                            "symbol": symbol,
                            "action": analysis['prediction'],
                            "confidence": analysis['confidence'],
                            "price": current_price
                        }
                        
                        risk_validation = risk_ai.validate_order(order_data, self.account_balance)
                        
                        # 4. Execução de Ordem
                        if risk_validation['valid']:
                            print(f"Sinal validado para {symbol}: {analysis['prediction']} ({analysis['confidence']:.2f})")
                            execution_result = await execution_engine.execute_order(risk_validation)
                            
                            if execution_result['status'] == "success":
                                print(f"Ordem executada com sucesso: {execution_result['order_id']}")
                                # Atualiza o saldo simulado (simplificado)
                                self.account_balance -= risk_validation['risk_amount']
                                
                await asyncio.sleep(60)  # Espera 1 minuto para o próximo ciclo
            except Exception as e:
                print(f"Erro no loop do motor de trading: {e}")
                await asyncio.sleep(10)

    def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        print("Motor de Trading ZIA parado.")

    def _get_historical_data(self, symbol: str) -> pd.DataFrame:
        """Simula a busca de dados históricos para análise."""
        # Em produção, buscaríamos do banco de dados (ex: PostgreSQL/InfluxDB)
        import numpy as np
        dates = pd.date_range(end=pd.Timestamp.now(), periods=100, freq='H')
        prices = np.random.uniform(50000, 60000, 100)
        return pd.DataFrame({'close': prices}, index=dates)

trading_engine = TradingEngine()
