import asyncio
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from config.settings import Settings
from infra.redis_cache import RedisCache
from ai.price_transformer_model import PriceTransformerModel
from ai.price_lstm_model import PriceLSTMModel
import torch
from risk.risk_ai import RiskAI
from execution.execution_engine import ExecutionEngine
from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector
from core.strategies.manager import StrategyManager

logger = logging.getLogger(__name__)

class RoboTraderUnified:
    """Motor de trading principal que coordena a análise e execução."""
    def __init__(self, settings: Settings, news_processor: NewsProcessor, exchange_connector: ExchangeConnector):
        self.settings = settings
        self.news_processor = news_processor
        self.is_running = False
        self.symbols = self.settings.SYMBOLS
        self.timeframe = self.settings.TIMEFRAME
        self.account_balance = 10000.0
        self.exchange_connector = exchange_connector
        self.strategy_manager = StrategyManager(self.settings)
        self.risk_ai = RiskAI(self.settings)
        self.redis_cache = RedisCache(self.settings.REDIS_URL)
        
        # Inicialização de modelos com tratamento de erro
        try:
            input_dim = 10
            d_model = 64
            nhead = 4
            num_encoder_layers = 2
            self.transformer_model = PriceTransformerModel(input_dim, d_model, nhead, num_encoder_layers)
            
            lstm_hidden_size = 128
            lstm_num_layers = 2
            lstm_output_size = 1
            self.lstm_model = PriceLSTMModel(input_dim, lstm_hidden_size, lstm_num_layers, lstm_output_size)
            self.execution_engine = ExecutionEngine()
        except Exception as e:
            logger.critical(f"Falha fatal na inicialização dos modelos de IA: {e}")
            raise

    async def start(self):
        """Inicia o motor de trading com resiliência a falhas de rede/API."""
        self.is_running = True
        logger.info("Motor de Trading ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Busca de dados com tratamento de erro específico por símbolo
                    try:
                        historical_data = await self.exchange_connector.get_historical_data(symbol, self.timeframe)
                        current_market_data = await self.exchange_connector.get_market_data(symbol)
                        current_price = current_market_data.get("last") if current_market_data else None
                    except Exception as e:
                        logger.error(f"Erro de conexão/API para {symbol}: {e}")
                        continue

                    if current_price is None:
                        logger.warning(f"[{symbol}] Preço indisponível. Pulando ciclo.")
                        continue

                    current_order_flow = {
                        "symbol": symbol,
                        "total_volume": current_market_data.get("volume", 0),
                        "buys": [],
                        "sells": []
                    }
                    
                    # 2. Pipeline de IA
                    input_dim = 10
                    if not historical_data.empty:
                        features = historical_data.select_dtypes(include=[np.number]).tail(30)
                        if features.shape[1] < input_dim:
                            input_tensor = torch.zeros(30, 1, input_dim)
                        else:
                            input_tensor = torch.tensor(features.values[-30:, :input_dim], dtype=torch.float32).unsqueeze(1)
                    else:
                        input_tensor = torch.zeros(30, 1, input_dim)

                    with torch.no_grad():
                        prediction_output = self.transformer_model(input_tensor)
                    
                    predicted_price_change = prediction_output[-1, 0, 0].item()
                    if predicted_price_change > 0.001:
                        prediction_action = "buy"
                        confidence = min(1.0, abs(predicted_price_change) * 100)
                    elif predicted_price_change < -0.001:
                        prediction_action = "sell"
                        confidence = min(1.0, abs(predicted_price_change) * 100)
                    else:
                        prediction_action = "hold"
                        confidence = 0.5

                    analysis = {"prediction": prediction_action, "confidence": confidence}

                    # 2.1. LSTM Analysis
                    if not historical_data.empty:
                        features_lstm = historical_data.select_dtypes(include=[np.number]).tail(30)
                        if features_lstm.shape[1] < input_dim:
                            input_tensor_lstm = torch.zeros(1, 30, input_dim)
                        else:
                            input_tensor_lstm = torch.tensor(features.values[-30:, :input_dim], dtype=torch.float32).unsqueeze(0)
                    else:
                        input_tensor_lstm = torch.zeros(1, 30, input_dim)

                    with torch.no_grad():
                        prediction_output_lstm = self.lstm_model(input_tensor_lstm)
                    
                    predicted_price_change_lstm = prediction_output_lstm[0, 0].item()
                    if predicted_price_change_lstm > 0.001:
                        prediction_action_lstm = "buy"
                        confidence_lstm = min(1.0, abs(predicted_price_change_lstm) * 100)
                    elif predicted_price_change_lstm < -0.001:
                        prediction_action_lstm = "sell"
                        confidence_lstm = min(1.0, abs(predicted_price_change_lstm) * 100)
                    else:
                        prediction_action_lstm = "hold"
                        confidence_lstm = 0.5
                    
                    if analysis["confidence"] > confidence_lstm:
                        final_prediction = analysis
                    else:
                        final_prediction = {"prediction": prediction_action_lstm, "confidence": confidence_lstm}
                    
                    logger.info(f"[{symbol}] Previsão FINAL: {final_prediction['prediction']} (Conf: {final_prediction['confidence']:.2f})")
                    analysis = final_prediction

                    # 3. Contexto de Mercado
                    try:
                        alpha_news = await self.news_processor.fetch_alpha_vantage_news(tickers=[symbol])
                        benzinga_news = await self.news_processor.fetch_benzinga_news(symbols=[symbol])
                        all_news = alpha_news + benzinga_news
                        processed_news = await self.news_processor.process_news_sentiment(all_news)
                        avg_sentiment = sum([n['sentiment_score'] for n in processed_news]) / len(processed_news) if processed_news else 0.0
                    except Exception as e:
                        logger.warning(f"Falha ao processar notícias para {symbol}: {e}")
                        avg_sentiment = 0.0

                    volume_analysis = self.risk_ai.analyze_volume_flow(historical_data)
                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "news_sentiment": avg_sentiment,
                        "volume_analysis": volume_analysis
                    }
                    
                    # 4. Risco e Execução
                    if analysis["prediction"] != "hold":
                        order_data = {
                            "symbol": symbol,
                            "action": analysis["prediction"],
                            "confidence": analysis["confidence"],
                            "price": current_price
                        }
                        
                        risk_validation = self.risk_ai.validate_order(order_data, self.account_balance, market_context)
                        
                        if risk_validation["valid"]:
                            try:
                                execution_result = await self.execution_engine.execute_order(risk_validation)
                                if execution_result["status"] == "success":
                                    logger.info(f"Ordem executada: {execution_result['order_id']}")
                            except Exception as e:
                                logger.error(f"Falha crítica na execução da ordem para {symbol}: {e}")
                                
                await asyncio.sleep(self.settings.TRADING_LOOP_INTERVAL)
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        logger.info("Motor de Trading ZIA parado.")
