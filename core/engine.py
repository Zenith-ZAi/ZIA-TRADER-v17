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
        self.account_balance = 10000.0  # Saldo inicial simulado
        self.exchange_connector = exchange_connector
        self.strategy_manager = StrategyManager(self.settings)
        self.risk_ai = RiskAI(self.settings)
        # self.sniper_engine = SniperEngine(self.settings, self.exchange_connector) # Removido, pois SniperEngine é gerenciado pelo TradingManager
        self.redis_cache = RedisCache(self.settings.REDIS_URL)
        # Inicializar o PriceTransformerModel
        # Parâmetros de exemplo, devem ser configurados via settings
        input_dim = 10  # Ex: OHLCV, indicadores
        d_model = 64
        nhead = 4
        num_encoder_layers = 2
        self.transformer_model = PriceTransformerModel(input_dim, d_model, nhead, num_encoder_layers)

        # Inicializar o PriceLSTMModel
        # Parâmetros de exemplo, devem ser configurados via settings
        lstm_hidden_size = 128
        lstm_num_layers = 2
        lstm_output_size = 1
        self.lstm_model = PriceLSTMModel(input_dim, lstm_hidden_size, lstm_num_layers, lstm_output_size)
        self.execution_engine = ExecutionEngine()

    async def start(self):
        """Inicia o motor de trading."""
        self.is_running = True
        logger.info("Motor de Trading ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Busca dados históricos e atuais via ExchangeConnector
                    historical_data = await self.exchange_connector.get_historical_data(symbol, self.timeframe)
                    current_market_data = await self.exchange_connector.get_market_data(symbol)
                    current_price = current_market_data.get("last") if current_market_data else None

                    if current_price is None:
                        logger.warning(f"[{symbol}] Não foi possível obter o preço atual. Pulando ciclo.")
                        continue

                    # Para o WhaleDetector, precisamos de um fluxo de ordens mais detalhado
                    # Isso exigiria uma integração de websocket ou API de Level 2/3, aqui simulamos
                    current_order_flow = {
                        "symbol": symbol,
                        "total_volume": current_market_data.get("volume", 0),
                        "buys": [], # Em um cenário real, preencheríamos com ordens de compra recentes
                        "sells": [] # Em um cenário real, preencheríamos com ordens de venda recentes
                    }
                    
                    # 2. Análise de IA (Transformer)
                    # Preparar dados para o modelo Transformer
                    # Em um cenário real, você precisaria de um pipeline de pré-processamento robusto
                    # Aqui, apenas um exemplo básico de como os dados seriam formatados
                    if not historical_data.empty:
                        # Exemplo: usar as últimas 'input_dim' colunas como features
                        # Ajuste isso conforme as features reais do seu modelo
                        features = historical_data.select_dtypes(include=[np.number]).tail(30) # Pegar últimas 30 entradas
                        if features.shape[1] < input_dim:
                            # Preencher com zeros ou levantar erro se as features não forem suficientes
                            logger.warning(f"[{symbol}] Número insuficiente de features para o Transformer. Esperado: {input_dim}, Encontrado: {features.shape[1]}")
                            input_tensor = torch.zeros(30, 1, input_dim) # Dummy tensor
                        else:
                            input_tensor = torch.tensor(features.values[-30:, :input_dim], dtype=torch.float32).unsqueeze(1) # (sequence_length, batch_size, input_dim)
                    else:
                        input_tensor = torch.zeros(30, 1, input_dim) # Dummy tensor

                    # Fazer a previsão
                    with torch.no_grad():
                        prediction_output = self.transformer_model(input_tensor)
                    
                    # Interpretar a saída do modelo (exemplo simplificado)
                    # Em um cenário real, você teria uma lógica mais complexa para converter a saída em 'buy', 'sell', 'hold'
                    predicted_price_change = prediction_output[-1, 0, 0].item() # Última previsão do último item do batch

                    if predicted_price_change > 0.001: # Exemplo de limiar
                        prediction_action = "buy"
                        confidence = min(1.0, abs(predicted_price_change) * 100) # Exemplo de confiança
                    elif predicted_price_change < -0.001:
                        prediction_action = "sell"
                        confidence = min(1.0, abs(predicted_price_change) * 100)
                    else:
                        prediction_action = "hold"
                        confidence = 0.5

                    analysis = {"prediction": prediction_action, "confidence": confidence}
                    logger.info(f"[{symbol}] Previsão do Transformer: {prediction_action} com confiança {confidence:.2f}")

                    # 2.1. Análise de IA (LSTM) - Exemplo de uso de outro modelo
                    # Preparar dados para o modelo LSTM
                    if not historical_data.empty:
                        features_lstm = historical_data.select_dtypes(include=[np.number]).tail(30) # Pegar últimas 30 entradas
                        if features_lstm.shape[1] < input_dim:
                            logger.warning(f"[{symbol}] Número insuficiente de features para o LSTM. Esperado: {input_dim}, Encontrado: {features.shape[1]}")
                            input_tensor_lstm = torch.zeros(1, 30, input_dim) # Dummy tensor (batch_size, sequence_length, input_size)
                        else:
                            input_tensor_lstm = torch.tensor(features.values[-30:, :input_dim], dtype=torch.float32).unsqueeze(0) # (batch_size, sequence_length, input_size)
                    else:
                        input_tensor_lstm = torch.zeros(1, 30, input_dim) # Dummy tensor

                    with torch.no_grad():
                        prediction_output_lstm = self.lstm_model(input_tensor_lstm)
                    
                    predicted_price_change_lstm = prediction_output_lstm[0, 0].item() # Última previsão

                    if predicted_price_change_lstm > 0.001:
                        prediction_action_lstm = "buy"
                        confidence_lstm = min(1.0, abs(predicted_price_change_lstm) * 100)
                    elif predicted_price_change_lstm < -0.001:
                        prediction_action_lstm = "sell"
                        confidence_lstm = min(1.0, abs(predicted_price_change_lstm) * 100)
                    else:
                        prediction_action_lstm = "hold"
                        confidence_lstm = 0.5
                    
                    logger.info(f"[{symbol}] Previsão do LSTM: {prediction_action_lstm} com confiança {confidence_lstm:.2f}")

                    # Exemplo de como combinar as previsões (pode ser mais sofisticado)
                    if analysis["confidence"] > confidence_lstm:
                        final_prediction = analysis
                    else:
                        final_prediction = {"prediction": prediction_action_lstm, "confidence": confidence_lstm}
                    
                    logger.info(f"[{symbol}] Previsão FINAL (Combinada): {final_prediction["prediction"]} com confiança {final_prediction["confidence"]:.2f}")

                    # Usar a previsão final para o gerenciamento de risco
                    analysis = final_prediction

                    
                    # 3. Análise de Contexto de Mercado (Notícias e Volume)
                    alpha_news = await self.news_processor.fetch_alpha_vantage_news(tickers=[symbol])
                    benzinga_news = await self.news_processor.fetch_benzinga_news(symbols=[symbol])
                    all_news = alpha_news + benzinga_news
                    processed_news = await self.news_processor.process_news_sentiment(all_news)
                    
                    avg_sentiment = sum([n['sentiment_score'] for n in processed_news]) / len(processed_news) if processed_news else 0.0
                    logger.info(f"Sentimento médio das notícias para {symbol}: {avg_sentiment:.2f}")

                    volume_analysis = self.risk_ai.analyze_volume_flow(historical_data)
                    
                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "news_sentiment": avg_sentiment, # Novo
                        "volume_analysis": volume_analysis
                    }
                    
                    # 4. Gerenciamento de Risco Cirúrgico
                    if analysis["prediction"] != "hold":
                        order_data = {
                            "symbol": symbol,
                            "action": analysis["prediction"],
                            "confidence": analysis["confidence"],
                            "price": current_price
                        }
                        
                        risk_validation = self.risk_ai.validate_order(order_data, self.account_balance, market_context)
                        
                        # 5. Execução de Ordem
                        if risk_validation["valid"]:
                            logger.info(f"Sinal validado para {symbol}: {analysis["prediction"]} ({analysis["confidence"]:.2f})")
                            execution_result = await self.execution_engine.execute_order(risk_validation)
                            
                            if execution_result["status"] == "success":
                                logger.info(f"Ordem executada com sucesso: {execution_result["order_id"]}")
                                # Atualiza o saldo simulado (simplificado)
                                # A execução real da ordem é feita pelo ExchangeConnector
                                # A atualização do saldo real e PnL seria feita após a confirmação da exchange
                                # self.account_balance -= risk_validation["risk_amount"] # Removido para execução real
                                # TODO: Implementar atualização de saldo real e PnL
                                
                    await asyncio.sleep(self.settings.TRADING_LOOP_INTERVAL)  # Espera o intervalo configurado para o próximo ciclo
            except Exception as e:
                logger.error(f"Erro no loop do motor de trading: {e}")
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        logger.info("Motor de Trading ZIA parado.")
