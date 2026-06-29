import asyncio
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any, Optional
from monitoring.metrics import TRADING_PNL, TRADING_BALANCE, TRADING_OPEN_POSITIONS, TRADING_ORDER_COUNT, TRADING_EXECUTION_LATENCY, AI_PREDICTION_CONFIDENCE, SYSTEM_ERROR_COUNT, SYSTEM_LOG_COUNT
from database import MarketType
from datetime import datetime, timedelta

from config.settings import Settings
from infra.redis_cache import RedisCache
from ai.price_transformer_model import PriceTransformerModel
from ai.price_lstm_model import PriceLSTMModel
from ai.ensemble_model import EnsembleModel
import torch
from risk.risk_ai import RiskAI
from execution.execution_engine import ExecutionEngine
from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector


logger = logging.getLogger(__name__)

class RoboTraderUnified:
    """Motor de trading principal que coordena a análise e execução."""
    def __init__(self, settings: Settings, news_processor: NewsProcessor, exchange_connector: ExchangeConnector, db_manager):
        self.settings = settings
        self.news_processor = news_processor
        self.is_running = False
        self.symbols = self.settings.SYMBOLS
        self.timeframe = self.settings.TIMEFRAME
        self.db_manager = db_manager
        self.account_id = "default_account" # Pode ser dinâmico em um sistema real
        account_state = self.db_manager.get_account_state(self.account_id)
        if not account_state:
            self.db_manager.create_or_update_account_state(self.account_id, 10000.0, 10000.0)
        self.account_balance = self.db_manager.get_account_state(self.account_id).balance
        TRADING_BALANCE.set(self.account_balance)
        self.exchange_connector = exchange_connector

        self.risk_ai = RiskAI(self.settings, self.db_manager)
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
            self.ensemble_model = EnsembleModel()
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
                        SYSTEM_LOG_COUNT.labels(level='WARNING').inc()
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
                    
                    # 2.2. Ensemble Analysis
                    ensemble_action, ensemble_confidence = "hold", 0.5
                    if not historical_data.empty:
                        # Preparar features para o ensemble (simplificado)
                        # Em produção, isso usaria um pipeline de feature engineering robusto
                        features_ensemble = historical_data.select_dtypes(include=[np.number]).tail(1)
                        # Preencher NaNs para evitar erros no predict
                        features_ensemble = features_ensemble.fillna(0)
                        
                        # Garantir que temos as features corretas (mock para evitar erro se não treinado)
                        if self.ensemble_model.is_trained:
                            try:
                                ensemble_action, ensemble_confidence = self.ensemble_model.predict(features_ensemble)
                            except Exception as e:
                                logger.warning(f"Erro ao prever com Ensemble: {e}")
                    
                    # Lógica de combinação final (votação ponderada simplificada)
                    predictions = [
                        {"action": analysis["prediction"], "confidence": analysis["confidence"], "weight": 0.3},
                        {"action": prediction_action_lstm, "confidence": confidence_lstm, "weight": 0.3},
                        {"action": ensemble_action, "confidence": ensemble_confidence, "weight": 0.4}
                    ]
                    
                    scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
                    for p in predictions:
                        scores[p["action"]] += p["confidence"] * p["weight"]
                    
                    final_action = max(scores, key=scores.get)
                    final_confidence = scores[final_action] / sum(p["weight"] for p in predictions)
                    
                    final_prediction = {"prediction": final_action, "confidence": final_confidence}
                    AI_PREDICTION_CONFIDENCE.set(final_confidence)
                    
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
                        
                        risk_validation = self.risk_ai.validate_order(order_data, self.db_manager.get_account_state(self.account_id).balance, market_context)
                        
                        if risk_validation["valid"]:
                            try:
                                execution_result = await self.execution_engine.execute_order(risk_validation)
                                if execution_result["status"] == "success":
                                    # Atualizar saldo e registrar execução
                                    current_balance = self.db_manager.get_account_state(self.account_id).balance
                                    new_balance = current_balance + (execution_result["filled_quantity"] * execution_result["filled_price"] * (-1 if order_data["action"] == "buy" else 1))
                                    self.db_manager.create_or_update_account_state(self.account_id, new_balance, self.db_manager.get_account_state(self.account_id).initial_capital)
                                    TRADING_BALANCE.set(new_balance)
                                    TRADING_PNL.set(new_balance - self.db_manager.get_account_state(self.account_id).initial_capital)
                                    TRADING_ORDER_COUNT.inc()
                                    self.db_manager.create_execution_history(
                                        account_id=self.account_id,
                                        execution_id=execution_result["order_id"], # Usando order_id como execution_id por simplicidade
                                        order_id=execution_result["order_id"],
                                        symbol=order_data["symbol"],
                                        market_type=MarketType.CRYPTO, # Assumindo crypto por enquanto
                                        action=order_data["action"],
                                        filled_price=execution_result["filled_price"],
                                        filled_quantity=execution_result["filled_quantity"],
                                        commission=execution_result.get("commission", 0.0)
                                    )
                                    logger.info(f"Ordem executada: {execution_result["order_id"]}")
                                    TRADING_OPEN_POSITIONS.inc() if order_data["action"] == "buy" else TRADING_OPEN_POSITIONS.dec()
                            except Exception as e:
                                logger.error(f"Falha crítica na execução da ordem para {symbol}: {e}")
                                self.db_manager.create_system_log("ERROR", f"Falha crítica na execução da ordem para {symbol}: {e}", "RoboTraderUnified")
                                SYSTEM_ERROR_COUNT.inc()
                                
                await asyncio.sleep(self.settings.TRADING_LOOP_INTERVAL)
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                SYSTEM_ERROR_COUNT.inc()
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        logger.info("Motor de Trading ZIA parado.")
        TRADING_OPEN_POSITIONS.set(0)
