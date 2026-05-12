import asyncio
import logging
from typing import Dict, Any

import numpy as np
import pandas as pd
import torch

from config.settings import Settings
from infra.redis_cache import RedisCache
from ai.price_transformer_model import PriceTransformerModel
from ai.price_lstm_model import PriceLSTMModel
from risk.risk_ai import RiskAI
from execution.execution_engine import ExecutionEngine
from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector
from core.strategies.manager import StrategyManager
from database import save_trade

logger = logging.getLogger(__name__)


class RoboTraderUnified:
    """Motor de trading principal que coordena a análise e execução."""

    def __init__(
        self,
        settings: Settings,
        news_processor: NewsProcessor,
        exchange_connector: ExchangeConnector,
    ):
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

        self.input_dim = 10
        d_model = 64
        nhead = 4
        num_encoder_layers = 2
        self.transformer_model = PriceTransformerModel(
            self.input_dim, d_model, nhead, num_encoder_layers
        )

        lstm_hidden_size = 128
        lstm_num_layers = 2
        lstm_output_size = 1
        self.lstm_model = PriceLSTMModel(
            self.input_dim, lstm_hidden_size, lstm_num_layers, lstm_output_size
        )
        self.execution_engine = ExecutionEngine()

    async def start(self):
        """Inicia o motor de trading."""
        self.is_running = True
        logger.info("Motor de Trading ZIA iniciado.")

        while self.is_running:
            try:
                for symbol in self.symbols:
                    historical_data = await self.exchange_connector.get_historical_data(
                        symbol, self.timeframe
                    )
                    current_market_data = await self.exchange_connector.get_market_data(
                        symbol
                    )
                    current_price = (
                        current_market_data.get("last") if current_market_data else None
                    )

                    if current_price is None:
                        logger.warning(
                            "[%s] Não foi possível obter o preço atual. Pulando ciclo.",
                            symbol,
                        )
                        continue

                    current_order_flow = {
                        "symbol": symbol,
                        "total_volume": current_market_data.get("volume", 0),
                        "buys": [],
                        "sells": [],
                    }

                    # --- Transformer prediction ---
                    if not historical_data.empty:
                        features = historical_data.select_dtypes(
                            include=[np.number]
                        ).tail(30)
                        if features.shape[1] < self.input_dim:
                            logger.warning(
                                "[%s] Features insuficientes para Transformer (%d/%d).",
                                symbol,
                                features.shape[1],
                                self.input_dim,
                            )
                            input_tensor = torch.zeros(30, 1, self.input_dim)
                        else:
                            input_tensor = torch.tensor(
                                features.values[-30:, : self.input_dim],
                                dtype=torch.float32,
                            ).unsqueeze(1)
                    else:
                        input_tensor = torch.zeros(30, 1, self.input_dim)

                    with torch.no_grad():
                        prediction_output = self.transformer_model(input_tensor)

                    predicted_change = prediction_output[-1, 0, 0].item()

                    if predicted_change > 0.001:
                        prediction_action = "buy"
                        confidence = min(1.0, abs(predicted_change) * 100)
                    elif predicted_change < -0.001:
                        prediction_action = "sell"
                        confidence = min(1.0, abs(predicted_change) * 100)
                    else:
                        prediction_action = "hold"
                        confidence = 0.5

                    analysis: Dict[str, Any] = {
                        "prediction": prediction_action,
                        "confidence": confidence,
                    }
                    logger.info(
                        "[%s] Transformer: %s (conf %.2f)",
                        symbol,
                        prediction_action,
                        confidence,
                    )

                    # --- LSTM prediction ---
                    if not historical_data.empty:
                        features_lstm = historical_data.select_dtypes(
                            include=[np.number]
                        ).tail(30)
                        if features_lstm.shape[1] < self.input_dim:
                            input_tensor_lstm = torch.zeros(1, 30, self.input_dim)
                        else:
                            input_tensor_lstm = torch.tensor(
                                features_lstm.values[-30:, : self.input_dim],
                                dtype=torch.float32,
                            ).unsqueeze(0)
                    else:
                        input_tensor_lstm = torch.zeros(1, 30, self.input_dim)

                    with torch.no_grad():
                        prediction_output_lstm = self.lstm_model(input_tensor_lstm)

                    predicted_change_lstm = prediction_output_lstm[0, 0].item()

                    if predicted_change_lstm > 0.001:
                        pred_lstm = "buy"
                        conf_lstm = min(1.0, abs(predicted_change_lstm) * 100)
                    elif predicted_change_lstm < -0.001:
                        pred_lstm = "sell"
                        conf_lstm = min(1.0, abs(predicted_change_lstm) * 100)
                    else:
                        pred_lstm = "hold"
                        conf_lstm = 0.5

                    logger.info(
                        "[%s] LSTM: %s (conf %.2f)", symbol, pred_lstm, conf_lstm
                    )

                    # Combine predictions — pick the one with higher confidence
                    if analysis["confidence"] >= conf_lstm:
                        final_prediction = analysis
                    else:
                        final_prediction = {
                            "prediction": pred_lstm,
                            "confidence": conf_lstm,
                        }

                    logger.info(
                        "[%s] Final: %s (conf %.2f)",
                        symbol,
                        final_prediction["prediction"],
                        final_prediction["confidence"],
                    )
                    analysis = final_prediction

                    # --- News sentiment ---
                    alpha_news = await self.news_processor.fetch_alpha_vantage_news(
                        tickers=[symbol]
                    )
                    benzinga_news = await self.news_processor.fetch_benzinga_news(
                        symbols=[symbol]
                    )
                    all_news = alpha_news + benzinga_news
                    processed_news = await self.news_processor.process_news_sentiment(
                        all_news
                    )

                    avg_sentiment = (
                        sum(n["sentiment_score"] for n in processed_news)
                        / len(processed_news)
                        if processed_news
                        else 0.0
                    )
                    logger.info(
                        "Sentimento médio para %s: %.2f", symbol, avg_sentiment
                    )

                    volume_analysis = self.risk_ai.analyze_volume_flow(historical_data)

                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "news_sentiment": avg_sentiment,
                        "volume_analysis": volume_analysis,
                    }

                    # --- Risk validation & execution ---
                    if analysis["prediction"] != "hold":
                        order_data = {
                            "symbol": symbol,
                            "action": analysis["prediction"],
                            "confidence": analysis["confidence"],
                            "price": current_price,
                        }

                        risk_validation = self.risk_ai.validate_order(
                            order_data, self.account_balance, market_context
                        )

                        if risk_validation["valid"]:
                            logger.info(
                                "Sinal validado para %s: %s (%.2f)",
                                symbol,
                                analysis["prediction"],
                                analysis["confidence"],
                            )
                            execution_result = (
                                await self.execution_engine.execute_order(
                                    risk_validation
                                )
                            )

                            if execution_result["status"] == "success":
                                logger.info(
                                    "Ordem executada: %s",
                                    execution_result["order_id"],
                                )
                                await save_trade(
                                    {
                                        "symbol": symbol,
                                        "action": analysis["prediction"],
                                        "quantity": risk_validation.get("quantity", 0),
                                        "price": current_price,
                                        "stop_loss": risk_validation.get("stop_loss"),
                                        "take_profit": risk_validation.get(
                                            "take_profit"
                                        ),
                                        "status": "open",
                                        "order_id": execution_result["order_id"],
                                    }
                                )

                await asyncio.sleep(self.settings.TRADING_LOOP_INTERVAL)
            except Exception as e:
                logger.error("Erro no loop do motor de trading: %s", e)
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    async def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        logger.info("Motor de Trading ZIA parado.")
