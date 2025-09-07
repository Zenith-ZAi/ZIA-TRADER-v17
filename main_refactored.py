import asyncio
import time
from datetime import datetime
import pandas as pd
from typing import Dict

from config import config
from utils import setup_logging
from enhanced_broker_api import EnhancedBrokerAPI
from ai_model_fixed import AdvancedAIModel
from quantum_analyzer import QuantumAnalyzer
from news_analyzer import NewsAnalyzer
from risk_management import AdvancedRiskManager
from order_execution import OrderExecutor
from database import db_manager, TradeRecord
from model_retraining_system import ModelRetrainingSystem

# Importar socketio para emitir eventos (assumindo que o backend Flask está rodando com SocketIO)
try:
    from flask_socketio import SocketIO
    socketio_instance = SocketIO(message_queue='redis://localhost:6379') # Usar Redis para message queue em produção
except ImportError:
    socketio_instance = None
    print("Flask-SocketIO não encontrado. Emissão de eventos em tempo real desabilitada.")

logger = setup_logging(__name__)

class RoboTrader:
    def __init__(self):
        self.is_running = False
        self.shutdown_requested = False
        self.symbols = config.data.symbols
        self.timeframe = config.data.timeframes[0]  # Usando o primeiro timeframe por padrão

        # Injeção de Dependência
        self.broker = EnhancedBrokerAPI(config.api.exchange_name, config.api.sandbox_mode)
        self.ai_model = AdvancedAIModel(input_shape=(config.ai.sequence_length, len(config.data.features)))
        self.quantum_analyzer = QuantumAnalyzer()
        self.news_analyzer = NewsAnalyzer()
        self.risk_manager = AdvancedRiskManager()
        self.order_executor = OrderExecutor(self.broker)
        self.model_retraining_system = ModelRetrainingSystem(self.ai_model, self.get_market_data_for_retraining)

        self.market_data_history = pd.DataFrame()
        self.performance_metrics = {}

    async def initialize(self) -> bool:
        logger.info("Iniciando RoboTrader 2.0...")
        if not await self.broker.connect():
            logger.error("Falha ao conectar com a corretora.")
            return False

        await self._load_initial_data()
        await self._initialize_ai_model()
        self.model_retraining_system.start_scheduler()
        
        if socketio_instance:
            socketio_instance.emit("system_status", {"status": "initialized", "message": "RoboTrader inicializado com sucesso"})
        return True

    async def _load_initial_data(self):
        logger.info("Carregando dados históricos iniciais...")
        for symbol in self.symbols:
            data = db_manager.get_market_data(symbol, self.timeframe, limit=config.ai.sequence_length + 200)
            if not data.empty:
                self.market_data_history = pd.concat([self.market_data_history, data], ignore_index=True)
        logger.info(f"{len(self.market_data_history)} registros históricos carregados.")

    async def _initialize_ai_model(self):
        logger.info("Inicializando modelo de IA...")
        if not self.ai_model.is_trained and not self.market_data_history.empty:
            await self.model_retraining_system.retrain_model_now()
        if socketio_instance:
            socketio_instance.emit("ai_model_status", {"is_trained": self.ai_model.is_trained, "metrics": self.ai_model.metrics})

    async def run(self):
        if not await self.initialize():
            logger.error("Falha na inicialização. Abortando...")
            return

        self.is_running = True
        logger.info("RoboTrader 2.0 iniciado - Loop principal ativo")
        if socketio_instance:
            socketio_instance.emit("system_status", {"status": "running", "message": "Loop principal ativo"})

        try:
            while self.is_running and not self.shutdown_requested:
                await self._run_iteration()
        except KeyboardInterrupt:
            logger.info("Interrupção manual detectada")
            if socketio_instance:
                socketio_instance.emit("system_status", {"status": "interrupted", "message": "Interrupção manual"})
        except Exception as e:
            logger.error(f"Erro crítico no loop principal: {e}")
            if socketio_instance:
                socketio_instance.emit("system_status", {"status": "error", "message": f"Erro crítico: {e}"})
        finally:
            await self._shutdown()

    async def _run_iteration(self):
        start_time = time.time()
        logger.info(f"\n---")
        logger.info(f"Iteração iniciada em {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}")

        for symbol in self.symbols:
            try:
                await self._analyze_and_trade(symbol)
            except Exception as e:
                logger.error(f"Erro ao processar {symbol}: {e}")

        await self._update_performance_metrics()

        execution_time = time.time() - start_time
        logger.info(f"Iteração concluída em {execution_time:.2f}s")
        if socketio_instance:
            socketio_instance.emit("iteration_complete", {"duration": execution_time})

        sleep_time = max(0, config.api.data_fetch_interval_seconds - execution_time)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    async def _analyze_and_trade(self, symbol: str):
        logger.info(f"Analisando {symbol}...")
        await self._update_market_data(symbol)

        if len(self.market_data_history) < config.ai.sequence_length + 50:
            logger.warning(f"Dados insuficientes para {symbol}")
            return

        current_data = self.market_data_history.tail(config.ai.sequence_length + 100).copy()

        ai_signal = await self._get_ai_signal(current_data)
        quantum_signal = self.quantum_analyzer.analyze_market_regime(current_data)
        news_sentiment = self.news_analyzer.analyze_sentiment(self.news_analyzer.get_market_news([symbol]))
        risk_assessment = self.risk_manager.assess_risk(symbol, ai_signal, quantum_signal, news_sentiment, current_data)

        await self._make_trading_decision(symbol, ai_signal, quantum_signal, news_sentiment, risk_assessment)

    async def _update_market_data(self, symbol: str):
        new_data = await self.broker.get_market_data_async(symbol, self.timeframe, 5)
        if not new_data.empty:
            db_manager.save_market_data(symbol, self.timeframe, new_data)
            self.market_data_history = pd.concat([self.market_data_history, new_data], ignore_index=True)
            self.market_data_history = self.market_data_history.tail(config.ai.sequence_length + 200).reset_index(drop=True)
            if socketio_instance:
                socketio_instance.emit("market_data_update", {"symbol": symbol, "data": new_data.to_dict(orient="records")})

    async def _get_ai_signal(self, data: pd.DataFrame) -> Dict:
        if not self.ai_model.is_trained:
            return {"action": "hold", "confidence": 0.0, "reason": "Modelo não treinado"}
        return self.ai_model.generate_advanced_signal(self.ai_model.predict(self.ai_model.prepare_data(data)[0][-1:]))

    async def _make_trading_decision(self, symbol: str, ai_signal: Dict, quantum_signal: Dict, news_sentiment: Dict, risk_assessment: Dict):
        account_balance = await self.broker.get_account_balance()
        if account_balance < config.trading.min_balance_for_trade:
            logger.warning(f"Saldo insuficiente para operar. Saldo atual: {account_balance:.2f}")
            if socketio_instance:
                socketio_instance.emit("alert", {"type": "warning", "message": f"Saldo insuficiente para operar. Saldo atual: {account_balance:.2f}"})
            return

        if self.risk_manager.consecutive_losses >= config.trading.consecutive_losses_limit:
            logger.critical("Circuit Breaker ativado: Limite de perdas consecutivas atingido.")
            self.shutdown_requested = True
            if socketio_instance:
                socketio_instance.emit("alert", {"type": "critical", "message": "Circuit Breaker ativado: Limite de perdas consecutivas atingido."})
            return

        action, confidence = self._get_final_action(ai_signal, quantum_signal, news_sentiment, risk_assessment)

        if action != "hold" and confidence >= config.trading.min_confidence / 100.0:
            order_amount = (account_balance * config.trading.max_position_size) / self.market_data_history["close"].iloc[-1]
            trade_id = await self.order_executor.execute_order(symbol=symbol, side=action, amount=order_amount, price=self.market_data_history["close"].iloc[-1])
            if trade_id:
                self._save_trade_record(symbol, action, order_amount, confidence, ai_signal, quantum_signal, news_sentiment, risk_assessment)
                if socketio_instance:
                    socketio_instance.emit("trade_executed", {"symbol": symbol, "side": action, "amount": order_amount, "trade_id": trade_id})
            else:
                if socketio_instance:
                    socketio_instance.emit("alert", {"type": "error", "message": f"Falha ao executar ordem {action.upper()} para {symbol}"})
        else:
            logger.info(f"Decisão: HOLD para {symbol} (Confiança: {confidence:.2f}, Risco: {risk_assessment["risk_level"]})")
            if socketio_instance:
                socketio_instance.emit("trade_decision", {"symbol": symbol, "action": "hold", "confidence": confidence, "risk_level": risk_assessment["risk_level"]})

    def _get_final_action(self, ai_signal, quantum_signal, news_sentiment, risk_assessment):
        action = ai_signal["action"]
        confidence = ai_signal["confidence"]

        if risk_assessment["risk_level"] == "high":
            return "hold", 0.0
        if quantum_signal["regime"] == "volatile":
            confidence *= 0.7
        if news_sentiment["overall_sentiment"] == "negative" and action == "buy":
            return "hold", 0.0

        return action, confidence

    def _save_trade_record(self, symbol, action, order_amount, confidence, ai_signal, quantum_signal, news_sentiment, risk_assessment):
        trade_record = TradeRecord(
            timestamp=datetime.now(),
            symbol=symbol,
            side=action,
            amount=order_amount,
            price=self.market_data_history["close"].iloc[-1],
            total_value=order_amount * self.market_data_history["close"].iloc[-1],
            strategy="combined_ai_quantum_news",
            confidence=confidence,
            ai_signal=ai_signal["action"],
            quantum_signal=quantum_signal["regime"],
            news_sentiment=news_sentiment["overall_sentiment"],
            risk_score=risk_assessment["risk_score"],
            status="executed"
        )
        db_manager.save_trade(trade_record)
        if socketio_instance:
            socketio_instance.emit("new_trade_record", trade_record.__dict__)

    async def _update_performance_metrics(self):
        recent_trades = db_manager.get_trades(limit=100)
        if recent_trades:
            df_trades = pd.DataFrame([t.to_dict() for t in recent_trades])
            total_pnl = df_trades["pnl"].sum()
            win_rate = (df_trades["pnl"] > 0).sum() / len(df_trades) * 100
            self.performance_metrics = {"total_pnl": total_pnl, "win_rate": win_rate, "last_update": datetime.now().isoformat()}
            db_manager.save_performance_metrics(self.performance_metrics)
            if socketio_instance:
                socketio_instance.emit("performance_update", self.performance_metrics)

    async def _shutdown(self):
        logger.info("Iniciando shutdown do RoboTrader...")
        self.is_running = False
        self.model_retraining_system.stop_scheduler()
        if socketio_instance:
            socketio_instance.emit("system_status", {"status": "shutdown", "message": "RoboTrader desligado"})

    def get_market_data_for_retraining(self):
        return self.market_data_history

async def main():
    trader = RoboTrader()
    await trader.run()

if __name__ == "__main__":
    asyncio.run(main())


