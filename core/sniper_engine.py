import asyncio
import pandas as pd
import numpy as np
import logging
import time
from typing import List, Dict, Any
from database import MarketType, OrderStatus
from datetime import datetime, timezone

from config.settings import Settings
from infra.redis_cache import RedisCache
from execution.execution_engine import ExecutionEngine
from ai.whale_detector import WhaleDetector
from core.market_signals import calculate_market_signal
from core.event_guard import EconomicEventGuard
from execution.exchange_connector import ExchangeConnector
from risk.risk_ai import RiskAI
from core.pullback_strategy import PullbackSignalCache
from core.pullback_registry import PullbackCacheRegistry
from core.decision_snapshot import build_decision_snapshot
from core.news_gate import evaluate_news_gate
from core.risk_guard import evaluate_circuit_breaker, evaluate_emergency_exit
from core.position_policy import evaluate_position_exit
from core.microstructure import estimate_entry_costs
from execution.cost_aware_executor import CostAwareExecutor
from monitoring.metrics import AI_LOCAL_DECISION_LATENCY

logger = logging.getLogger(__name__)

class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""
    def __init__(self, settings: Settings, exchange_connector: ExchangeConnector, execution_engine: ExecutionEngine, whale_detector: WhaleDetector, redis_cache: RedisCache, db_manager, news_processor=None, pullback_registry: PullbackCacheRegistry | None = None):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.execution_engine = execution_engine
        self.whale_detector = whale_detector
        self.redis_cache = redis_cache
        self.pullback_registry = pullback_registry or PullbackCacheRegistry()
        self.db_manager = db_manager
        self.news_processor = news_processor
        self.account_id = "default_account" # Pode ser dinâmico em um sistema real
        self.risk_ai = RiskAI(settings, db_manager)
        self.cost_aware_executor = CostAwareExecutor(
            max_spread_bps=float(settings.MAX_SPREAD_BPS),
            max_slippage_bps=float(settings.MAX_ESTIMATED_SLIPPAGE_BPS),
            max_book_impact=float(settings.MAX_BOOK_IMPACT),
        )
        self.event_guard = EconomicEventGuard(
            settings.ECONOMIC_EVENTS_FILE,
            settings.EVENT_BLOCK_BEFORE_SECONDS,
            settings.EVENT_BLOCK_AFTER_SECONDS,
        )
        self.is_running = False
        self.symbols = self.settings.SYMBOLS
        self.volatility_threshold = self.settings.SNIPER_VOLATILITY_THRESHOLD  # Ex: 2% de variação em 1 minuto

    def refresh_runtime_config(self) -> None:
        self.symbols = self.settings.SYMBOLS
        logger.info("Configuração do Sniper atualizada: símbolos=%s timeframe=%s", self.symbols, self.settings.SNIPER_TIMEFRAME)

    async def start(self):
        """Inicia o motor Sniper."""
        self.is_running = True
        logger.info("Motor Sniper ZIA iniciado.")
        
        decision_lease = None
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Monitoramento de Volatilidade em Tempo Real
                    current_market_data = await self.exchange_connector.get_market_data(symbol)
                    historical_data = await self.exchange_connector.get_historical_data(
                        symbol,
                        self.settings.SNIPER_TIMEFRAME,
                        limit=max(250, int(self.settings.PULLBACK_EMA_PERIOD) + 30),
                    )
                    current_price = current_market_data.get("last") if current_market_data else None
                    
                    if current_price is None:
                        logger.warning(f"[{symbol}] Sniper: Não foi possível obter o preço atual. Pulando ciclo.")
                        continue

                    lock_key = f"zia:decision-lock:{self.account_id}:{symbol}:{self.settings.SNIPER_TIMEFRAME}"
                    decision_lease = await self.redis_cache.acquire_lock(
                        lock_key,
                        ttl_seconds=int(getattr(self.settings, "DECISION_LOCK_TTL_SECONDS", 30)),
                        renew_seconds=int(getattr(self.settings, "DECISION_LOCK_RENEW_SECONDS", 10)),
                    )
                    if decision_lease is None:
                        logger.warning("[%s] Sniper: concorrência evitada; lock não adquirido.", symbol)
                        self.db_manager.create_system_log("INFO", f"Concorrência Sniper evitada para {symbol}", "SniperEngine", self.account_id)
                        continue

                    live_position = await self.redis_cache.get_state(f"position_{symbol}")
                    if live_position and self.settings.AUTONOMOUS_TRADING_ENABLED:
                        exit_decision = evaluate_position_exit(
                            live_position,
                            current_price,
                            high=current_market_data.get("high", current_price),
                            low=current_market_data.get("low", current_price),
                        )
                        if exit_decision.get("should_exit"):
                            try:
                                exchange_balances = await self.exchange_connector.get_account_balance()
                            except Exception:
                                exchange_balances = {}
                            exit_payload = {**live_position, "symbol": symbol, "exit_reason": exit_decision.get("reason")}
                            exit_validation = self.risk_ai.validate_exit(exit_payload, exit_decision["price"], {"exchange_balances": exchange_balances})
                            if exit_validation.get("valid"):
                                exit_result = await self.execution_engine.execute_order(exit_validation)
                                if exit_result.get("status") == "success":
                                    logger.info("Sniper: posição fechada por %s", exit_decision.get("reason"))

                    previous_price_key = f"prev_price_sniper_{symbol}"
                    previous_price = await self.redis_cache.get_state(previous_price_key)
                    
                    if previous_price:
                        price_change = abs(current_price - float(previous_price)) / float(previous_price)
                        
                        # 2.1. Detecção de atividade concentrada no livro de ordens
                        order_book = await self.exchange_connector.get_order_book(symbol, limit=20)
                        current_order_flow = {
                            "symbol": symbol,
                            "total_volume": current_market_data.get("volume", 0),
                            "buys": order_book.get("bids", []),
                            "sells": order_book.get("asks", []),
                            "last_update_id": order_book.get("last_update_id"),
                        }
                        whale_activity = self.whale_detector.detect_whale_activity(historical_data, current_order_flow)
                        whale_detected = bool(
                            whale_activity.get("detected")
                            and whale_activity.get("magnitude", 0.0) >= self.settings.WHALE_ACTIVITY_SNIPER_THRESHOLD
                        )
                        if whale_detected:
                            logger.info("Sniper: baleia detectada para %s; magnitude=%.3f", symbol, whale_activity["magnitude"])

                        # 2.2. Volatilidade só vira entrada quando há confluência real.
                        if price_change > self.volatility_threshold:
                            sniper_started = time.perf_counter()
                            action = "buy" if current_price > float(previous_price) else "sell"
                            processed_news = []
                            trends = []
                            if self.news_processor is not None:
                                try:
                                    processed_news = await self.news_processor.fetch_all([symbol])
                                    trends = await self.news_processor.fetch_trending([symbol])
                                except Exception as exc:
                                    logger.warning("Sniper: falha em notícias/tendências para %s: %s", symbol, exc)
                            news_sentiment = self.news_processor.aggregate_sentiment(processed_news) if self.news_processor is not None else 0.0
                            trend_score = float(trends[0].get("trend_score", 0.0)) if trends else 0.0
                            news_health = self.news_processor.health() if self.news_processor is not None else {}
                            news_gate = evaluate_news_gate(processed_news, news_health, self.settings)
                            pullback_signal_cached = None
                            if self.settings.PULLBACK_STRATEGY_ENABLED:
                                pullback_signal_cached = self.pullback_registry.latest_signal(
                                    symbol,
                                    self.settings.SNIPER_TIMEFRAME,
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
                                )
                            market_signal = calculate_market_signal(
                                historical_data,
                                news_sentiment=news_sentiment,
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
                            whale_direction_matches = (
                                (action == "buy" and whale_activity.get("sentiment") == "bullish")
                                or (action == "sell" and whale_activity.get("sentiment") == "bearish")
                            )
                            pullback_ok = not self.settings.PULLBACK_STRATEGY_ENABLED or market_signal.pullback.get("action") == action
                            event_status = self.event_guard.blocked(datetime.now(timezone.utc), symbol)
                            account_state = self.db_manager.get_account_state(self.account_id)
                            daily_pnl_obj = self.db_manager.get_daily_pnl(self.account_id, datetime.now(timezone.utc).replace(tzinfo=None))
                            circuit_breaker = evaluate_circuit_breaker(
                                float(account_state.balance if account_state else 0.0),
                                float(account_state.initial_capital if account_state else 0.0),
                                float(daily_pnl_obj.pnl if daily_pnl_obj else 0.0),
                                self.settings,
                            )
                            emergency_exit = evaluate_emergency_exit(event_status, news_gate, market_signal, self.settings)
                            estimated_stop = current_price * (1.0 - float(self.settings.STOP_LOSS_PCT)) if action == "buy" else current_price * (1.0 + float(self.settings.STOP_LOSS_PCT))
                            estimated_target = current_price * (1.0 + float(self.settings.TAKE_PROFIT_PCT)) if action == "buy" else current_price * (1.0 - float(self.settings.TAKE_PROFIT_PCT))
                            microstructure = estimate_entry_costs(
                                current_market_data,
                                current_order_flow,
                                action,
                                float(self.settings.SNIPER_TRADE_QUANTITY),
                                current_price,
                                estimated_stop,
                                estimated_target,
                                self.settings,
                            )
                            cost_estimate = self.cost_aware_executor.estimate(
                                current_market_data | current_order_flow,
                                action,
                                float(self.settings.SNIPER_TRADE_QUANTITY),
                            )
                            if self.settings.COST_AWARE_EXECUTION_ENABLED and not cost_estimate["allowed"]:
                                microstructure["allowed"] = False
                                microstructure["reasons"].append(cost_estimate["reason"])
                            microstructure["cost_aware"] = cost_estimate
                            spot_direction_allowed = bool(self.settings.ALLOW_SHORT or action == "buy")
                            entry_allowed = live_position is None
                            confirmed_event = bool(
                                self.settings.AUTONOMOUS_TRADING_ENABLED
                                and spot_direction_allowed
                                and entry_allowed
                                and whale_detected
                                and whale_direction_matches
                                and market_signal.action == action
                                and market_signal.confidence >= float(self.settings.MIN_CONFIDENCE_THRESHOLD)
                                and pullback_ok
                                and news_gate["entry_allowed"]
                                and not circuit_breaker["tripped"]
                                and microstructure["allowed"]
                                and not event_status.get("blocked", False)
                            )
                            sniper_latency_ms = (time.perf_counter() - sniper_started) * 1000.0
                            AI_LOCAL_DECISION_LATENCY.observe(sniper_latency_ms / 1000.0)
                            shadow_action = action if whale_detected and whale_direction_matches and market_signal.action == action and market_signal.confidence >= float(self.settings.MIN_CONFIDENCE_THRESHOLD) and pullback_ok and news_gate["entry_allowed"] and not circuit_breaker["tripped"] and microstructure["allowed"] and not event_status.get("blocked", False) else "hold"
                            if self.settings.SHADOW_MODE_ENABLED:
                                self.db_manager.create_ai_observation({
                                    "symbol": symbol,
                                    "mode": "sniper-shadow",
                                    "action": shadow_action,
                                    "candidate_action": action,
                                    "confidence": min(float(market_signal.confidence), float(whale_activity.get("confidence", 0.0))),
                                    "model_action": market_signal.action,
                                    "model_confidence": market_signal.confidence,
                                    "market_signal_action": market_signal.action,
                                    "market_signal_confidence": market_signal.confidence,
                                    "price": current_price,
                                    "news_sentiment": news_sentiment,
                                    "trend_score": trend_score,
                                    "event_blocked": bool(event_status.get("blocked", False)),
                                    "risk_valid": False,
                                    "decision_latency_ms": sniper_latency_ms,
                                    "metadata_json": {
                                        "price_change": price_change,
                                        "volatility_threshold": self.volatility_threshold,
                                        "whale_activity": whale_activity,
                                        "pullback_signal": market_signal.pullback,
                                        "event_guard": event_status,
                                        "news_gate": news_gate,
                                        "circuit_breaker": circuit_breaker,
                                        "microstructure": microstructure,
                                        "emergency_exit": emergency_exit,
                                        "live_position": live_position or {},
                                        "spot_direction_allowed": spot_direction_allowed,
                                        "autonomous_enabled": self.settings.AUTONOMOUS_TRADING_ENABLED,
                                    },
                                })
                                self.db_manager.create_decision_snapshot(build_decision_snapshot(
                                    symbol=symbol,
                                    timeframe=self.settings.SNIPER_TIMEFRAME,
                                    mode="sniper-shadow",
                                    action=shadow_action,
                                    candidate_action=action,
                                    confidence=min(float(market_signal.confidence), float(whale_activity.get("confidence", 0.0))),
                                    gate_status="allowed" if microstructure.get("allowed") and news_gate.get("entry_allowed") and not circuit_breaker.get("tripped") else "blocked",
                                    before_context={
                                        "price": current_price,
                                        "price_change": price_change,
                                        "news_sentiment": news_sentiment,
                                        "trend_score": trend_score,
                                        "whale_activity": whale_activity,
                                        "market_signal": market_signal.to_dict(),
                                        "pullback_signal": market_signal.pullback,
                                        "event_guard": event_status,
                                        "news_gate": news_gate,
                                        "circuit_breaker": circuit_breaker,
                                        "microstructure": microstructure,
                                        "order_flow": current_order_flow,
                                    },
                                    feature_context=market_signal.to_dict(),
                                ))
                            logger.info(
                                "Sniper: evento=%s ação=%s sinal=%s confiança=%.2f confirmado=%s",
                                symbol,
                                action,
                                market_signal.action,
                                market_signal.confidence,
                                confirmed_event,
                            )
                            if confirmed_event:
                                order_data = {
                                    "symbol": symbol,
                                    "action": action,
                                    "quantity": self.settings.SNIPER_TRADE_QUANTITY,
                                    "price": current_price,
                                    "confidence": min(float(market_signal.confidence), float(whale_activity.get("confidence", 0.0))),
                                    "market_type": MarketType.FOREX if str(self.settings.MARKET_ADAPTER).lower() == "forex" else MarketType.CRYPTO,
                                }
                                account_state = self.db_manager.get_account_state(self.account_id)
                                try:
                                    exchange_balances = await self.exchange_connector.get_account_balance()
                                except Exception as exc:
                                    logger.warning("Sniper: saldo privado indisponível para %s: %s", symbol, exc)
                                    exchange_balances = {}
                                account_balance = self.risk_ai.quote_equivalent_balance(exchange_balances, symbol, current_price) or (account_state.balance if account_state else 0.0)
                                risk_context = {
                                    "historical_data": historical_data,
                                    "exchange_balances": exchange_balances,
                                    "market_signal": market_signal.to_dict(),
                                    "whale_activity": whale_activity,
                                    "current_order_flow": current_order_flow,
                                    "microstructure": microstructure,
                                }
                                risk_validation = self.risk_ai.validate_order(
                                    order_data,
                                    account_balance,
                                    risk_context,
                                )
                                if risk_validation["valid"] and self.settings.COST_AWARE_EXECUTION_ENABLED:
                                    adjusted_cost = self.cost_aware_executor.adjust_quantity(
                                        current_market_data | current_order_flow,
                                        action,
                                        float(risk_validation.get("quantity", 0.0)),
                                    )
                                    adjusted_quantity = float(adjusted_cost.get("adjusted_quantity", 0.0))
                                    if adjusted_quantity <= 0.0:
                                        risk_validation = {"valid": False, "reason": adjusted_cost["reason"], "cost_aware": adjusted_cost}
                                    else:
                                        risk_validation["quantity"] = adjusted_quantity
                                        risk_validation["cost_aware"] = adjusted_cost
                                if not risk_validation["valid"]:
                                    logger.warning("Sniper: ordem rejeitada por risco para %s: %s", symbol, risk_validation["reason"])
                                else:
                                    execution_order = {**order_data, **risk_validation}
                                    execution_result = await self.execution_engine.execute_order(execution_order)
                                    if execution_result["status"] == "success":
                                        logger.info("Sniper: Ordem executada com sucesso: %s", execution_result["order_id"])
                                        self.db_manager.create_execution_history(
                                            account_id=self.account_id,
                                            execution_id=execution_result["order_id"],
                                            order_id=execution_result["order_id"],
                                            symbol=order_data["symbol"],
                                            market_type=order_data.get("market_type", MarketType.CRYPTO),
                                            action=order_data["action"],
                                            filled_price=execution_result["filled_price"],
                                            filled_quantity=execution_result["filled_quantity"],
                                            commission=execution_result.get("commission", 0.0),
                                        )
                                
                    # 5. Atualiza o preço anterior no cache Redis
                    await self.redis_cache.set_state(previous_price_key, str(current_price), expire=self.settings.SNIPER_PRICE_CACHE_EXPIRE)
                    if decision_lease is not None:
                        await decision_lease.release()
                        decision_lease = None
                    
                await asyncio.sleep(self.settings.SNIPER_CYCLE_INTERVAL_SECONDS)  # Ciclo rápido configurável
            except Exception as e:
                if decision_lease is not None:
                    await decision_lease.release()
                    decision_lease = None
                logger.error(f"Erro no loop do motor Sniper: {e}")
                self.db_manager.create_system_log("ERROR", f"Erro no loop do motor Sniper: {e}", "SniperEngine")
                await asyncio.sleep(self.settings.ERROR_RETRY_INTERVAL)

    async def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        logger.info("Motor Sniper ZIA parado.")
