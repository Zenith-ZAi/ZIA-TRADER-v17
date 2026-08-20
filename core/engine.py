import asyncio
import pandas as pd
import numpy as np
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from monitoring.metrics import TRADING_PNL, TRADING_BALANCE, TRADING_OPEN_POSITIONS, TRADING_ORDER_COUNT, TRADING_EXECUTION_LATENCY, AI_PREDICTION_CONFIDENCE, AI_LOCAL_DECISION_LATENCY, AI_NEWS_FETCH_LATENCY, SYSTEM_ERROR_COUNT, SYSTEM_LOG_COUNT
from database import MarketType
from datetime import datetime, timedelta, timezone

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
from core.event_guard import EconomicEventGuard
from core.pullback_strategy import PullbackSignalCache
from core.pattern_memory import PatternMemory, build_pattern_signature
from core.position_policy import evaluate_position_exit
from core.multi_timeframe import combine_timeframe_signals, parse_timeframes
from core.news_gate import evaluate_news_gate
from core.risk_guard import evaluate_circuit_breaker, evaluate_emergency_exit
from core.microstructure import estimate_entry_costs
from execution.cost_aware_executor import CostAwareExecutor


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
        self.autonomy_blocked = bool(
            self.settings.AUTONOMOUS_TRADING_ENABLED
            and self.settings.REDIS_REQUIRED_FOR_AUTONOMOUS
            and not self.redis_cache.is_persistent
        )
        if self.autonomy_blocked:
            logger.critical("Autonomia bloqueada: Redis persistente é obrigatório para manter posições live.")
        self.event_guard = EconomicEventGuard(
            self.settings.ECONOMIC_EVENTS_FILE,
            self.settings.EVENT_BLOCK_BEFORE_SECONDS,
            self.settings.EVENT_BLOCK_AFTER_SECONDS,
        )
        self.pattern_memory = PatternMemory(self.db_manager, self.settings)
        self.cost_aware_executor = CostAwareExecutor(
            max_spread_bps=float(self.settings.MAX_SPREAD_BPS),
            max_slippage_bps=float(self.settings.MAX_ESTIMATED_SLIPPAGE_BPS),
            max_book_impact=float(self.settings.MAX_BOOK_IMPACT),
        )
        
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
            self.ensemble_model = EnsembleModel(self.settings.ENSEMBLE_MODEL_DIR)
            self.execution_engine = ExecutionEngine(
                self.settings,
                self.exchange_connector,
                self.redis_cache,
                db_manager=self.db_manager,
                account_id=self.account_id,
            )
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

    def refresh_runtime_config(self) -> None:
        self.symbols = self.settings.SYMBOLS
        self.timeframe = self.settings.TIMEFRAME
        logger.info("Configuração do motor principal atualizada: símbolos=%s timeframe=%s", self.symbols, self.timeframe)

    async def reconcile_runtime_positions(self) -> int:
        restored = 0
        for position in self.db_manager.get_open_runtime_positions(self.account_id):
            key = f"position_{position.symbol}"
            if await self.redis_cache.get_state(key) is None:
                await self.redis_cache.set_state(key, {
                    "symbol": position.symbol,
                    "action": position.action,
                    "quantity": position.quantity,
                    "entry_price": position.entry_price,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                    "breakeven_trigger": position.breakeven_trigger,
                    "status": "open",
                    "order_id": position.order_id,
                })
                restored += 1
        if restored:
            logger.warning("%s posição(ões) restaurada(s) do estado persistente.", restored)
        return restored

    async def start(self):
        """Inicia o motor de trading com resiliência a falhas de rede/API."""
        self.is_running = True
        await self.reconcile_runtime_positions()
        logger.info("Motor de Trading ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Busca de dados com tratamento de erro específico por símbolo
                    try:
                        historical_data = await self.exchange_connector.get_historical_data(
                            symbol,
                            self.timeframe,
                            limit=max(250, int(self.settings.PULLBACK_EMA_PERIOD) + 30),
                        )
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
                    model_compute_started = time.perf_counter()
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
                    model_compute_latency_ms = (time.perf_counter() - model_compute_started) * 1000.0

                    # 3. Contexto de Mercado e gate de confluência
                    news_started = time.perf_counter()
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
                    news_provider_health = self.news_processor.health() if hasattr(self.news_processor, "health") else {}
                    news_gate = evaluate_news_gate(processed_news, news_provider_health, self.settings)
                    news_latency_ms = (time.perf_counter() - news_started) * 1000.0
                    AI_NEWS_FETCH_LATENCY.observe(news_latency_ms / 1000.0)
                    signal_compute_started = time.perf_counter()

                    pullback_signal_cached = None
                    if self.settings.PULLBACK_STRATEGY_ENABLED:
                        pullback_signal_cached = PullbackSignalCache(
                            historical_data,
                            ema_period=int(self.settings.PULLBACK_EMA_PERIOD),
                            rsi_period=int(self.settings.PULLBACK_RSI_PERIOD),
                            atr_period=int(self.settings.PULLBACK_ATR_PERIOD),
                            volume_period=int(self.settings.PULLBACK_VOLUME_PERIOD),
                            touch_tolerance=float(self.settings.PULLBACK_TOUCH_TOLERANCE),
                            exhaustion_volume_ratio=float(self.settings.PULLBACK_EXHAUSTION_VOLUME_RATIO),
                            trigger_volume_ratio=float(self.settings.PULLBACK_TRIGGER_VOLUME_RATIO),
                            stop_atr_multiple=float(self.settings.PULLBACK_STOP_ATR_MULTIPLE),
                            target_atr_multiple=float(self.settings.PULLBACK_TARGET_ATR_MULTIPLE),
                            breakeven_atr_trigger=float(self.settings.PULLBACK_BREAKEVEN_ATR_TRIGGER),
                        ).at(len(historical_data) - 1)
                    market_signal = calculate_market_signal(
                        historical_data,
                        news_sentiment=avg_sentiment,
                        trend_score=trend_score,
                        min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                        max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                        pullback_kwargs={
                            "ema_period": int(self.settings.PULLBACK_EMA_PERIOD),
                            "rsi_period": int(self.settings.PULLBACK_RSI_PERIOD),
                            "atr_period": int(self.settings.PULLBACK_ATR_PERIOD),
                            "volume_period": int(self.settings.PULLBACK_VOLUME_PERIOD),
                            "touch_tolerance": float(self.settings.PULLBACK_TOUCH_TOLERANCE),
                            "exhaustion_volume_ratio": float(self.settings.PULLBACK_EXHAUSTION_VOLUME_RATIO),
                            "trigger_volume_ratio": float(self.settings.PULLBACK_TRIGGER_VOLUME_RATIO),
                            "stop_atr_multiple": float(self.settings.PULLBACK_STOP_ATR_MULTIPLE),
                            "target_atr_multiple": float(self.settings.PULLBACK_TARGET_ATR_MULTIPLE),
                            "breakeven_atr_trigger": float(self.settings.PULLBACK_BREAKEVEN_ATR_TRIGGER),
                        },
                        precomputed_pullback=pullback_signal_cached,
                    )
                    timeframe_signals = {self.timeframe: market_signal}
                    if self.settings.MULTI_TIMEFRAME_ENABLED:
                        for timeframe in parse_timeframes(self.settings.ANALYSIS_TIMEFRAMES, self.timeframe):
                            if timeframe == self.timeframe:
                                continue
                            try:
                                timeframe_data = await self.exchange_connector.get_historical_data(
                                    symbol,
                                    timeframe,
                                    limit=max(250, int(self.settings.PULLBACK_EMA_PERIOD) + 30),
                                )
                                timeframe_signals[timeframe] = calculate_market_signal(
                                    timeframe_data,
                                    news_sentiment=avg_sentiment,
                                    trend_score=trend_score,
                                    min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                                    max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                                )
                            except Exception as exc:
                                logger.warning("[%s] Falha no timeframe %s: %s", symbol, timeframe, exc)
                    multi_timeframe = combine_timeframe_signals(
                        timeframe_signals,
                        self.timeframe,
                        int(self.settings.MULTI_TIMEFRAME_MIN_CONFIRMATIONS),
                    )
                    multi_timeframe_ok = not self.settings.MULTI_TIMEFRAME_ENABLED or multi_timeframe["confirmed"]
                    reversal_signal = detect_reversal_signal(
                        historical_data,
                        news_sentiment=avg_sentiment,
                        trend_score=trend_score,
                        min_confidence=float(self.settings.MIN_CONFIDENCE_THRESHOLD),
                        max_volatility=float(self.settings.BACKTEST_MAX_VOLATILITY),
                    )
                    model_action = final_action
                    model_confidence = final_confidence
                    pattern_signature = build_pattern_signature(historical_data, market_signal, avg_sentiment, trend_score)
                    pattern_match = self.pattern_memory.find_match(symbol, pattern_signature)
                    pattern_ok = not self.pattern_memory.enabled or pattern_match.matched
                    pullback_action = market_signal.pullback.get("action", "hold")
                    pullback_ok = not self.settings.PULLBACK_STRATEGY_ENABLED or pullback_action == model_action
                    event_status = self.event_guard.blocked(datetime.now(timezone.utc), symbol)
                    event_ok = not event_status.get("blocked", False)
                    if market_signal.action in {"buy", "sell"} and market_signal.action == model_action and pullback_ok and pattern_ok and event_ok and multi_timeframe_ok and news_gate["entry_allowed"]:
                        final_action = model_action
                        final_confidence = min(1.0, (model_confidence + market_signal.confidence) / 2.0)
                    else:
                        final_action = "hold"
                        final_confidence = min(model_confidence, market_signal.confidence)
                    final_prediction = {"prediction": final_action, "confidence": final_confidence}
                    signal_compute_latency_ms = (time.perf_counter() - signal_compute_started) * 1000.0
                    local_decision_latency_ms = model_compute_latency_ms + signal_compute_latency_ms
                    AI_LOCAL_DECISION_LATENCY.observe(local_decision_latency_ms / 1000.0)
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
                    daily_pnl_obj = self.db_manager.get_daily_pnl(self.account_id, datetime.now(timezone.utc).replace(tzinfo=None))
                    daily_pnl = float(daily_pnl_obj.pnl) if daily_pnl_obj else 0.0
                    circuit_breaker = evaluate_circuit_breaker(
                        account_balance,
                        float(account_state.initial_capital if account_state else 0.0),
                        daily_pnl,
                        self.settings,
                    )
                    estimated_action = analysis["prediction"] if analysis["prediction"] in {"buy", "sell"} else "buy"
                    estimated_quantity = (
                        account_balance * float(self.settings.MAX_RISK_PER_TRADE)
                        / max(current_price * float(self.settings.STOP_LOSS_PCT), 1e-12)
                    )
                    estimated_stop = current_price * (1.0 - float(self.settings.STOP_LOSS_PCT)) if estimated_action == "buy" else current_price * (1.0 + float(self.settings.STOP_LOSS_PCT))
                    estimated_target = current_price * (1.0 + float(self.settings.TAKE_PROFIT_PCT)) if estimated_action == "buy" else current_price * (1.0 - float(self.settings.TAKE_PROFIT_PCT))
                    microstructure = estimate_entry_costs(
                        current_market_data,
                        current_order_flow,
                        estimated_action,
                        estimated_quantity,
                        current_price,
                        estimated_stop,
                        estimated_target,
                        self.settings,
                    )
                    cost_estimate = self.cost_aware_executor.estimate(
                        current_market_data | current_order_flow,
                        estimated_action,
                        estimated_quantity,
                    )
                    if self.settings.COST_AWARE_EXECUTION_ENABLED and not cost_estimate["allowed"]:
                        microstructure["allowed"] = False
                        microstructure["reasons"].append(cost_estimate["reason"])
                    microstructure["cost_aware"] = cost_estimate
                    live_position = await self.redis_cache.get_state(f"position_{symbol}")
                    exit_decision = evaluate_position_exit(
                        live_position,
                        current_price,
                        high=current_market_data.get("high", current_price),
                        low=current_market_data.get("low", current_price),
                        market_signal=market_signal,
                        reversal_signal=reversal_signal,
                    )
                    emergency_exit = evaluate_emergency_exit(event_status, news_gate, market_signal, self.settings)
                    if live_position and emergency_exit["should_exit"]:
                        exit_decision = {
                            "should_exit": True,
                            "reason": emergency_exit["reason"],
                            "exit_action": "sell" if live_position.get("action") == "buy" else "buy",
                            "price": current_price,
                        }
                    market_context = {
                        "historical_data": historical_data,
                        "current_order_flow": current_order_flow,
                        "exchange_balances": exchange_balances,
                        "news_sentiment": avg_sentiment,
                        "trend_score": trend_score,
                        "news_count": len(processed_news),
                        "market_signal": market_signal.to_dict(),
                        "reversal_signal": reversal_signal,
                        "pullback_signal": market_signal.pullback,
                        "event_guard": event_status,
                        "news_gate": news_gate,
                        "multi_timeframe": multi_timeframe,
                        "microstructure": microstructure,
                        "volume_analysis": volume_analysis,
                    }
                    shadow_order_data = {
                        "symbol": symbol,
                        "action": analysis["prediction"],
                        "confidence": analysis["confidence"],
                        "price": current_price,
                    }
                    shadow_risk = {"valid": False, "reason": "sinal HOLD"}
                    if analysis["prediction"] in {"buy", "sell"}:
                        shadow_risk = self.risk_ai.validate_order(shadow_order_data, account_balance, market_context)
                    if self.settings.SHADOW_MODE_ENABLED:
                        feature_snapshot = {}
                        if not model_features.empty:
                            feature_snapshot = {key: float(value) for key, value in model_features.tail(1).iloc[0].to_dict().items() if np.isfinite(float(value))}
                        self.db_manager.create_ai_observation({
                            "symbol": symbol,
                            "mode": "shadow",
                            "action": analysis["prediction"],
                            "candidate_action": market_signal.candidate_action,
                            "confidence": analysis["confidence"],
                            "model_action": model_action,
                            "model_confidence": model_confidence,
                            "market_signal_action": market_signal.action,
                            "market_signal_confidence": market_signal.confidence,
                            "price": current_price,
                            "news_sentiment": avg_sentiment,
                            "trend_score": trend_score,
                            "event_blocked": bool(event_status.get("blocked", False)),
                            "risk_valid": bool(shadow_risk.get("valid", False)),
                            "decision_latency_ms": local_decision_latency_ms,
                            "news_latency_ms": news_latency_ms,
                            "metadata_json": {
                                "model_compute_latency_ms": model_compute_latency_ms,
                                "signal_compute_latency_ms": signal_compute_latency_ms,
                                "news_count": len(processed_news),
                                "news_provider_health": self.news_processor.health(),
                                "regime": market_signal.regime,
                                "reversal_signal": reversal_signal,
                                "pullback_signal": market_signal.pullback,
                                "event_guard": event_status,
                                "news_gate": news_gate,
                                "multi_timeframe": multi_timeframe,
                                "circuit_breaker": circuit_breaker,
                                "microstructure": microstructure,
                                "emergency_exit": emergency_exit,
                                "pattern_signature": pattern_signature,
                                "pattern_match": pattern_match.to_dict(),
                                "live_position": live_position or {},
                                "exit_decision": exit_decision,
                                "volume_analysis": volume_analysis,
                                "features": feature_snapshot,
                                "risk_reason": shadow_risk.get("reason", ""),
                            },
                        })
                    
                    # 4. Risco e Execução: primeiro fecha; somente depois pode avaliar nova entrada.
                    exit_executed = False
                    if live_position and exit_decision.get("should_exit") and self.settings.AUTONOMOUS_TRADING_ENABLED:
                        exit_position = {**live_position, "symbol": symbol, "exit_reason": exit_decision.get("reason")}
                        exit_validation = self.risk_ai.validate_exit(exit_position, exit_decision["price"], {"exchange_balances": exchange_balances})
                        if exit_validation.get("valid"):
                            exit_result = await self.execution_engine.execute_order(exit_validation)
                            if exit_result.get("status") == "success":
                                await self.redis_cache.delete_state(f"position_{symbol}")
                                self.db_manager.close_position(self.account_id, symbol)
                                exit_executed = True
                                logger.info("[%s] Posição fechada por %s", symbol, exit_decision.get("reason"))
                        else:
                            logger.warning("[%s] Saída rejeitada pelo RiskAI: %s", symbol, exit_validation.get("reason"))
                    entry_allowed = live_position is None and not exit_executed
                    spot_direction_allowed = bool(self.settings.ALLOW_SHORT or analysis["prediction"] == "buy")
                    safety_entry_allowed = bool(
                        not self.autonomy_blocked
                        and not circuit_breaker["tripped"]
                        and news_gate["entry_allowed"]
                        and multi_timeframe_ok
                        and microstructure["allowed"]
                    )
                    if analysis["prediction"] != "hold" and self.settings.AUTONOMOUS_TRADING_ENABLED and entry_allowed and spot_direction_allowed and safety_entry_allowed:
                        order_data = {
                            "symbol": symbol,
                            "action": analysis["prediction"],
                            "confidence": analysis["confidence"],
                            "price": current_price,
                            "market_type": MarketType.FOREX if str(self.settings.MARKET_ADAPTER).lower() == "forex" else MarketType.CRYPTO,
                        }
                        
                        risk_validation = self.risk_ai.validate_order(order_data, account_balance, market_context)
                        if risk_validation["valid"] and self.settings.COST_AWARE_EXECUTION_ENABLED:
                            adjusted_cost = self.cost_aware_executor.adjust_quantity(
                                current_market_data | current_order_flow,
                                order_data["action"],
                                float(risk_validation.get("quantity", 0.0)),
                            )
                            adjusted_quantity = float(adjusted_cost.get("adjusted_quantity", 0.0))
                            if adjusted_quantity <= 0.0:
                                risk_validation = {"valid": False, "reason": adjusted_cost["reason"], "cost_aware": adjusted_cost}
                            else:
                                risk_validation["quantity"] = adjusted_quantity
                                risk_validation["cost_aware"] = adjusted_cost
                        
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
                                        market_type=order_data.get("market_type", MarketType.CRYPTO),
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
