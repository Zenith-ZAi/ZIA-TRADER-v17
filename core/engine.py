import asyncio
import pandas as pd
import numpy as np
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from monitoring.metrics import TRADING_PNL, TRADING_BALANCE, TRADING_OPEN_POSITIONS, TRADING_ORDER_COUNT, TRADING_EXECUTION_LATENCY, AI_PREDICTION_CONFIDENCE, SYSTEM_ERROR_COUNT, SYSTEM_LOG_COUNT
from database import MarketType
from datetime import datetime, timedelta

from config.settings import Settings
from infra.redis_cache import RedisCache
from ai.price_transformer_model import PriceTransformerModel
from ai.price_lstm_model import PriceLSTMModel
from ai.ensemble_model import EnsembleModel
from ai.feature_pipeline import build_feature_frame
import torch
from risk.risk_ai import RiskAI
from execution.execution_engine import ExecutionEngine
from data.news_processor import NewsProcessor
from execution.exchange_connector import ExchangeConnector
from core.market_signals import calculate_market_signal, detect_reversal_signal


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
            input_dim = self.settings.TRANSFORMER_INPUT_DIM
            d_model = self.settings.TRANSFORMER_D_MODEL
            nhead = self.settings.TRANSFORMER_NHEAD
            num_encoder_layers = self.settings.TRANSFORMER_NUM_ENCODER_LAYERS
            self.transformer_model = PriceTransformerModel(input_dim, d_model, nhead, num_encoder_layers)
            
            lstm_hidden_size = self.settings.LSTM_HIDDEN_DIM
            lstm_num_layers = self.settings.LSTM_NUM_LAYERS
            lstm_output_size = self.settings.LSTM_OUTPUT_DIM
            self.lstm_model = PriceLSTMModel(input_dim, lstm_hidden_size, lstm_num_layers, lstm_output_size)
            self.neural_models_ready = self._load_neural_weights()
            self.ensemble_model = EnsembleModel()
            self.execution_engine = ExecutionEngine(self.settings, self.exchange_connector, self.redis_cache)
        except Exception as e:
            logger.critical(f"Falha fatal na inicialização dos modelos de IA: {e}")
            raise

    def _load_neural_weights(self) -> bool:
        if not self.settings.NEURAL_MODELS_ENABLED:
            return False
        transformer_path = Path(self.settings.TRANSFORMER_WEIGHTS_PATH)
        lstm_path = Path(self.settings.LSTM_WEIGHTS_PATH)
        if not transformer_path.exists() or not lstm_path.exists():
            logger.warning("Pesos Transformer/LSTM ausentes; redes neurais permanecerão desativadas.")
            return False
        try:
            self.transformer_model.load_state_dict(torch.load(transformer_path, map_location="cpu"))
            self.lstm_model.load_state_dict(torch.load(lstm_path, map_location="cpu"))
            logger.info("Pesos Transformer/LSTM carregados com sucesso.")
            return True
        except Exception as exc:
            logger.error("Pesos neurais rejeitados: %s", exc)
            return False

    @staticmethod
    def _price_change_to_signal(value: float) -> tuple[str, float]:
        if value > 0.001:
            return "buy", min(1.0, abs(value) * 100)
        if value < -0.001:
            return "sell", min(1.0, abs(value) * 100)
        return "hold", 0.0

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

                    order_book = await self.exchange_connector.get_order_book(symbol, limit=20)
                    current_order_flow = {
                        "symbol": symbol,
                        "total_volume": current_market_data.get("volume", 0),
                        "buys": order_book.get("bids", []),
                        "sells": order_book.get("asks", []),
                        "last_update_id": order_book.get("last_update_id"),
                    }
                    
                    # 2. Pipeline de IA com features causais compartilhadas
                    input_dim = self.settings.TRANSFORMER_INPUT_DIM
                    model_features = pd.DataFrame()
                    try:
                        model_features = build_feature_frame(historical_data).dropna()
                    except (TypeError, ValueError) as exc:
                        logger.warning("[%s] Features de modelo indisponíveis: %s", symbol, exc)

                    prediction_action = "hold"
                    confidence = 0.0
                    prediction_action_lstm = "hold"
                    confidence_lstm = 0.0
                    if self.neural_models_ready and len(model_features) >= self.settings.TRANSFORMER_SEQ_LEN:
                        sequence = model_features.tail(self.settings.TRANSFORMER_SEQ_LEN).to_numpy(dtype=np.float32)
                        if sequence.shape[1] != input_dim:
                            logger.error("[%s] Schema neural incompatível: %s != %s", symbol, sequence.shape[1], input_dim)
                        else:
                            input_tensor = torch.tensor(sequence, dtype=torch.float32).unsqueeze(1)
                            input_tensor_lstm = input_tensor.transpose(0, 1)
                            self.transformer_model.eval()
                            self.lstm_model.eval()
                            with torch.no_grad():
                                prediction_output = self.transformer_model(input_tensor)
                                prediction_output_lstm = self.lstm_model(input_tensor_lstm)
                            predicted_price_change = float(prediction_output[-1, 0, 0].item())
                            predicted_price_change_lstm = float(prediction_output_lstm[0, 0].item())
                            prediction_action, confidence = self._price_change_to_signal(predicted_price_change)
                            prediction_action_lstm, confidence_lstm = self._price_change_to_signal(predicted_price_change_lstm)

                    ensemble_action, ensemble_confidence = "hold", 0.0
                    if self.ensemble_model.is_trained and not model_features.empty:
                        try:
                            ensemble_action, ensemble_confidence = self.ensemble_model.predict(model_features.tail(1))
                        except Exception as exc:
                            logger.warning("Erro ao prever com Ensemble: %s", exc)

                    predictions = []
                    if self.neural_models_ready:
                        predictions.extend([
                            {"action": prediction_action, "confidence": confidence, "weight": 0.3},
                            {"action": prediction_action_lstm, "confidence": confidence_lstm, "weight": 0.3},
                        ])
                    if self.ensemble_model.is_trained:
                        predictions.append({"action": ensemble_action, "confidence": ensemble_confidence, "weight": 0.4})

                    if not predictions:
                        final_action, final_confidence = "hold", 0.0
                    else:
                        scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
                        total_weight = sum(p["weight"] for p in predictions)
                        for prediction in predictions:
                            scores[prediction["action"]] += prediction["confidence"] * prediction["weight"]
                        final_action = max(scores, key=scores.get)
                        final_confidence = scores[final_action] / total_weight

                    # 3. Contexto de Mercado e gate de confluência
                    try:
                        processed_news = await self.news_processor.fetch_all([symbol])
                        trends = await self.news_processor.fetch_trending([symbol])
                        avg_sentiment = self.news_processor.aggregate_sentiment(processed_news)
                        trend_score = float(trends[0].get("trend_score", 0.0)) if trends else 0.0
                    except Exception as e:
                        logger.warning(f"Falha ao processar notícias/tendências para {symbol}: {e}")
                        processed_news = []
                        avg_sentiment = 0.0
                        trend_score = 0.0

                    market_signal = calculate_market_signal(
                        historical_data,
                        news_sentiment=avg_sentiment,
                        trend_score=trend_score,
                        min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                        max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                    )
                    reversal_signal = detect_reversal_signal(
                        historical_data,
                        news_sentiment=avg_sentiment,
                        trend_score=trend_score,
                        min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                        max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                    )
                    model_action = final_action
                    model_confidence = final_confidence
                    if market_signal.action in {"buy", "sell"} and market_signal.action == model_action:
                        final_action = model_action
                        final_confidence = min(1.0, (model_confidence + market_signal.confidence) / 2.0)
                    else:
                        final_action = "hold"
                        final_confidence = min(model_confidence, market_signal.confidence)
                    final_prediction = {"prediction": final_action, "confidence": final_confidence}
                    AI_PREDICTION_CONFIDENCE.set(final_confidence)
                    logger.info(
                        "[%s] Sinal=%s candidato=%s confiança=%.2f regime=%s motivos=%s",
                        symbol,
                        market_signal.action,
                        market_signal.candidate_action,
                        market_signal.confidence,
                        market_signal.regime,
                        "; ".join(market_signal.reasons),
                    )
                    analysis = final_prediction

                    volume_analysis = self.risk_ai.analyze_volume_flow(historical_data)
                    try:
                        exchange_balances = await self.exchange_connector.get_account_balance()
                    except Exception as exc:
                        logger.warning("[%s] Saldo privado indisponível para sizing: %s", symbol, exc)
                        exchange_balances = {}
                    account_state = self.db_manager.get_account_state(self.account_id)
                    account_balance = self.risk_ai.quote_equivalent_balance(exchange_balances, symbol, current_price) or (account_state.balance if account_state else 0.0)
                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "exchange_balances": exchange_balances,
                        "news_sentiment": avg_sentiment,
                        "trend_score": trend_score,
                        "news_count": len(processed_news),
                        "market_signal": market_signal.to_dict(),
                        "reversal_signal": reversal_signal,
                        "volume_analysis": volume_analysis
                    }
                    
                    # 4. Risco e Execução
                    if analysis["prediction"] != "hold" and self.settings.AUTONOMOUS_TRADING_ENABLED:
                        order_data = {
                            "symbol": symbol,
                            "action": analysis["prediction"],
                            "confidence": analysis["confidence"],
                            "price": current_price,
                        }
                        
                        risk_validation = self.risk_ai.validate_order(order_data, account_balance, market_context)
                        
                        if risk_validation["valid"]:
                            try:
                                execution_order = {**order_data, **risk_validation}
                                execution_result = await self.execution_engine.execute_order(execution_order)
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
                                    logger.info("Ordem executada: %s", execution_result["order_id"])
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

    async def stop(self):
        """Para o motor de trading."""
        self.is_running = False
        logger.info("Motor de Trading ZIA parado.")
        TRADING_OPEN_POSITIONS.set(0)
