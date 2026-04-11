import asyncio
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime
from config.settings import settings
from infra.redis_cache import redis_cache
from ai.transformer_model import transformer_model
from risk.risk_ai import risk_ai
from execution.execution_engine import execution_engine
from data.news_processor import news_processor

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
                    current_order_flow = self._get_current_order_flow(symbol)
                    # Em produção, buscaríamos do banco de dados ou API
                    historical_data = self._get_historical_data(symbol)
                    current_price = redis_cache.get_price(symbol)
                    
                    # 2. Análise de IA (Transformer)
                    analysis = transformer_model.predict(historical_data)
                    
                    # 3. Análise de Contexto de Mercado (Notícias e Volume)
                    news_articles = await news_processor.fetch_latest_news(symbol)
                    news_impact = news_processor.analyze_impact(news_articles)
                    volume_analysis = risk_ai.analyze_volume_flow(historical_data)
                    
                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "news_impact": news_impact,
                        "volume_analysis": volume_analysis,
                        "candle_pattern": self._detect_candle_pattern(historical_data),
                        "atr": self._calculate_atr(historical_data)
                    }
                    
                    # 4. Gerenciamento de Risco Cirúrgico
                    if analysis['prediction'] != "hold":
                        order_data = {
                            "symbol": symbol,
                            "action": analysis['prediction'],
                            "confidence": analysis['confidence'],
                            "price": current_price
                        }
                        
                        risk_validation = risk_ai.validate_order(order_data, self.account_balance, market_context)
                        
                        # 5. Execução de Ordem
                        if risk_validation['valid']:
                            print(f"Sinal validado para {symbol}: {analysis['prediction']} ({analysis['confidence']:.2f})")
                            execution_result = await execution_engine.execute_order(risk_validation)
                            
                            if execution_result['status'] == "success":
                                print(f"Ordem executada com sucesso: {execution_result['order_id']}")
                                # Atualiza o saldo simulado (simplificado)
                                self.account_balance -= risk_validation["risk_amount"]
                                # TODO: Implementar atualização de saldo real e PnL
                                
                await asyncio.sleep(settings.TRADING_CYCLE_INTERVAL_SECONDS)  # Espera o intervalo configurado para o próximo ciclo
            except Exception as e:
                print(f"Erro no loop do motor de trading: {e}")
                await asyncio.sleep(10)

    def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        print("Motor de Trading ZIA parado.")

    def _get_historical_data(self, symbol: str) -> pd.DataFrame:
        """Simula a busca de dados históricos para análise."""
        import numpy as np
        dates = pd.date_range(end=pd.Timestamp.now(), periods=100, freq='H')
        prices = np.random.uniform(50000, 60000, 100)
        volumes = np.random.uniform(100, 1000, 100)
        return pd.DataFrame({'close': prices, 'volume': volumes, 'open': prices*0.99, 'high': prices*1.01, 'low': prices*0.98}, index=dates)

    def _detect_candle_pattern(self, df: pd.DataFrame) -> str:
        """Detecta padrões de vela para confirmação cirúrgica."""
        # Simulação de detecção de padrões (ex: TA-Lib)
        return "strong_uptrend" if df['close'].iloc[-1] > df['close'].iloc[-2] else "neutral"

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """Calcula o Average True Range para Stop Loss dinâmico."""
        return (df["high"] - df["low"]).mean()

    def _get_current_order_flow(self, symbol: str) -> Dict[str, Any]:
        """Simula o fluxo de ordens atual para detecção de baleias."""
        # Em produção, isso viria de um feed de dados de nível 2 ou 3
        return {
            "volume": np.random.uniform(100, 2000),
            "order_size": np.random.uniform(1000, 200000),
            "timestamp": datetime.now()
        }

trading_engine = TradingEngine()
