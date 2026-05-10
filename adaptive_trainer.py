"""
learning/adaptive_trainer.py

Sistema de Aprendizado Adaptativo do ZIA TRADER v17.

Função: A cada ciclo semanal (configurável), coleta métricas reais
de performance, avalia o que funcionou, ajusta os parâmetros do
sistema e retreina os modelos com dados novos.

Integração:
  TradingManager → AdaptiveTrainer.run_cycle()
  ExecutionEngine → fornece trade_history e métricas
  RiskAI         → recebe novos parâmetros ajustados
  LSTM/Transformer → retreinados com dados recentes
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Avaliador de Performance ─────────────────────────────────────────────────

class PerformanceEvaluator:
    """
    Analisa o histórico de trades e extrai métricas para o ciclo de aprendizado.
    """

    def evaluate(self, trade_history: List[Dict]) -> Dict[str, Any]:
        if not trade_history:
            return self._empty_metrics()

        pnls       = [t.get("pnl", 0.0) for t in trade_history]
        wins       = [p for p in pnls if p > 0]
        losses     = [p for p in pnls if p <= 0]
        total      = len(pnls)
        win_rate   = len(wins) / total if total > 0 else 0.0
        avg_win    = float(np.mean(wins))   if wins   else 0.0
        avg_loss   = float(np.mean(losses)) if losses else 0.0
        total_pnl  = float(np.sum(pnls))
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Sharpe ratio simplificado (sem taxa livre de risco)
        std_pnl = float(np.std(pnls)) if len(pnls) > 1 else 1.0
        sharpe  = (float(np.mean(pnls)) / std_pnl) * (252 ** 0.5) if std_pnl > 0 else 0.0

        # Max drawdown a partir da curva de capital
        cumulative  = np.cumsum(pnls)
        peak        = np.maximum.accumulate(cumulative)
        drawdown    = peak - cumulative
        max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        # Melhores e piores símbolos
        by_symbol: Dict[str, List[float]] = {}
        for t in trade_history:
            sym = t.get("symbol", "unknown")
            by_symbol.setdefault(sym, []).append(t.get("pnl", 0.0))

        symbol_pnl = {s: float(np.sum(v)) for s, v in by_symbol.items()}
        best_symbol  = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None
        worst_symbol = min(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None

        return {
            "total_trades":   total,
            "win_rate":       round(win_rate, 4),
            "avg_win":        round(avg_win, 4),
            "avg_loss":       round(avg_loss, 4),
            "profit_factor":  round(profit_factor, 4),
            "sharpe_ratio":   round(sharpe, 4),
            "total_pnl":      round(total_pnl, 4),
            "max_drawdown":   round(max_drawdown, 4),
            "best_symbol":    best_symbol,
            "worst_symbol":   worst_symbol,
            "symbol_breakdown": symbol_pnl,
            "evaluated_at":   datetime.utcnow().isoformat()
        }

    def _empty_metrics(self) -> Dict:
        return {
            "total_trades": 0, "win_rate": 0.0, "avg_win": 0.0,
            "avg_loss": 0.0, "profit_factor": 0.0, "sharpe_ratio": 0.0,
            "total_pnl": 0.0, "max_drawdown": 0.0, "best_symbol": None,
            "worst_symbol": None, "symbol_breakdown": {},
            "evaluated_at": datetime.utcnow().isoformat()
        }


# ─── Ajustador de Parâmetros ──────────────────────────────────────────────────

class ParameterOptimizer:
    """
    Ajusta os parâmetros do RiskAI e do engine com base nos resultados reais.
    Usa lógica de regras adaptativas — não gradiente, para manter interpretabilidade.
    """

    def optimize(self, metrics: Dict, current_params: Dict) -> Tuple[Dict, List[str]]:
        """
        Retorna (novos_params, lista_de_ajustes_realizados).
        """
        params  = current_params.copy()
        actions = []

        win_rate     = metrics.get("win_rate", 0.0)
        max_drawdown = metrics.get("max_drawdown", 0.0)
        profit_factor= metrics.get("profit_factor", 1.0)
        sharpe       = metrics.get("sharpe_ratio", 0.0)
        total_pnl    = metrics.get("total_pnl", 0.0)

        # ── Regras de ajuste de risco ──────────────────────────────

        # Win rate muito baixo → reduz risco por trade
        if win_rate < 0.40:
            old = params.get("MAX_RISK_PER_TRADE", 0.02)
            params["MAX_RISK_PER_TRADE"] = max(0.005, old * 0.85)
            actions.append(f"↓ MAX_RISK_PER_TRADE: {old:.3f} → {params['MAX_RISK_PER_TRADE']:.3f} (win_rate baixo: {win_rate:.1%})")

        # Win rate alto e drawdown baixo → pode aumentar risco levemente
        elif win_rate > 0.60 and max_drawdown < 500:
            old = params.get("MAX_RISK_PER_TRADE", 0.02)
            params["MAX_RISK_PER_TRADE"] = min(0.05, old * 1.10)
            actions.append(f"↑ MAX_RISK_PER_TRADE: {old:.3f} → {params['MAX_RISK_PER_TRADE']:.3f} (performance forte)")

        # Drawdown alto → ativa modo conservador
        if max_drawdown > 1000:
            old = params.get("MIN_AI_CONFIDENCE", 0.70)
            params["MIN_AI_CONFIDENCE"] = min(0.95, old + 0.05)
            actions.append(f"↑ MIN_AI_CONFIDENCE: {old:.2f} → {params['MIN_AI_CONFIDENCE']:.2f} (drawdown alto: ${max_drawdown:.0f})")

        # Sharpe ratio bom → relaxa threshold de confiança levemente
        elif sharpe > 1.5 and win_rate > 0.55:
            old = params.get("MIN_AI_CONFIDENCE", 0.70)
            params["MIN_AI_CONFIDENCE"] = max(0.60, old - 0.02)
            actions.append(f"↓ MIN_AI_CONFIDENCE: {old:.2f} → {params['MIN_AI_CONFIDENCE']:.2f} (Sharpe: {sharpe:.2f})")

        # Profit factor < 1 → aumenta filtro de notícias
        if profit_factor < 1.0:
            old = params.get("MIN_NEWS_SENTIMENT_FOR_BUY", 0.3)
            params["MIN_NEWS_SENTIMENT_FOR_BUY"] = min(0.6, old + 0.05)
            actions.append(f"↑ MIN_NEWS_SENTIMENT_FOR_BUY: {old:.2f} → {params['MIN_NEWS_SENTIMENT_FOR_BUY']:.2f}")

        # Sem ajustes necessários
        if not actions:
            actions.append("✓ Parâmetros mantidos — performance dentro dos limites ideais.")

        return params, actions


# ─── Retreinador de Modelos ───────────────────────────────────────────────────

class ModelRetrainer:
    """
    Retreina os modelos LSTM e Transformer com dados recentes.
    Salva os pesos em disco para persistência entre reinicializações.
    """

    MODEL_DIR = "models/weights"

    def __init__(self):
        os.makedirs(self.MODEL_DIR, exist_ok=True)

    async def retrain(
        self,
        historical_data: pd.DataFrame,
        lstm_model,
        transformer_model,
        epochs: int = 10
    ) -> Dict[str, Any]:
        """
        Retreina ambos os modelos com dados recentes.
        Roda em thread separada para não bloquear o event loop.
        """
        if historical_data.empty or len(historical_data) < 50:
            logger.warning("Dados insuficientes para retreinamento (mínimo 50 candles).")
            return {"status": "skipped", "reason": "dados insuficientes"}

        result = await asyncio.to_thread(
            self._retrain_sync, historical_data, lstm_model, transformer_model, epochs
        )
        return result

    def _retrain_sync(self, df: pd.DataFrame, lstm_model, transformer_model, epochs: int) -> Dict:
        """Lógica de treino síncrona executada em thread."""
        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim

            # Prepara features: OHLCV + retornos
            features = self._prepare_features(df)
            if features is None:
                return {"status": "error", "reason": "falha na preparação de features"}

            X, y = self._build_sequences(features, seq_len=30)
            if len(X) < 10:
                return {"status": "skipped", "reason": "sequências insuficientes"}

            X_tensor = torch.tensor(X, dtype=torch.float32)
            y_tensor = torch.tensor(y, dtype=torch.float32).unsqueeze(1)

            results = {}

            # ── Retreina LSTM ──────────────────────────────────────
            try:
                optimizer = optim.Adam(lstm_model.parameters(), lr=1e-4)
                criterion = nn.MSELoss()
                lstm_model.train()
                lstm_losses = []

                for epoch in range(epochs):
                    optimizer.zero_grad()
                    output = lstm_model(X_tensor)
                    loss   = criterion(output, y_tensor)
                    loss.backward()
                    nn.utils.clip_grad_norm_(lstm_model.parameters(), 1.0)
                    optimizer.step()
                    lstm_losses.append(loss.item())

                lstm_model.eval()
                lstm_path = os.path.join(self.MODEL_DIR, "lstm_latest.pt")
                torch.save(lstm_model.state_dict(), lstm_path)
                results["lstm"] = {
                    "final_loss":    round(lstm_losses[-1], 6),
                    "initial_loss":  round(lstm_losses[0], 6),
                    "improvement":   round(lstm_losses[0] - lstm_losses[-1], 6),
                    "epochs":        epochs,
                    "saved_to":      lstm_path
                }
                logger.info(f"✅ LSTM retreinado | Loss: {lstm_losses[0]:.6f} → {lstm_losses[-1]:.6f}")
            except Exception as e:
                results["lstm"] = {"status": "error", "reason": str(e)}
                logger.error(f"Erro ao retreinar LSTM: {e}")

            # ── Retreina Transformer ───────────────────────────────
            try:
                # Transformer espera (seq_len, batch, features)
                X_trans = X_tensor.permute(1, 0, 2)
                optimizer_t = optim.Adam(transformer_model.parameters(), lr=1e-4)
                criterion_t = nn.MSELoss()
                transformer_model.train()
                trans_losses = []

                for epoch in range(epochs):
                    optimizer_t.zero_grad()
                    output_t = transformer_model(X_trans)
                    loss_t   = criterion_t(output_t[-1].squeeze(), y_tensor.squeeze())
                    loss_t.backward()
                    nn.utils.clip_grad_norm_(transformer_model.parameters(), 1.0)
                    optimizer_t.step()
                    trans_losses.append(loss_t.item())

                transformer_model.eval()
                trans_path = os.path.join(self.MODEL_DIR, "transformer_latest.pt")
                torch.save(transformer_model.state_dict(), trans_path)
                results["transformer"] = {
                    "final_loss":   round(trans_losses[-1], 6),
                    "initial_loss": round(trans_losses[0], 6),
                    "improvement":  round(trans_losses[0] - trans_losses[-1], 6),
                    "epochs":       epochs,
                    "saved_to":     trans_path
                }
                logger.info(f"✅ Transformer retreinado | Loss: {trans_losses[0]:.6f} → {trans_losses[-1]:.6f}")
            except Exception as e:
                results["transformer"] = {"status": "error", "reason": str(e)}
                logger.error(f"Erro ao retreinar Transformer: {e}")

            results["status"]        = "success"
            results["samples_used"]  = len(X)
            results["completed_at"]  = datetime.utcnow().isoformat()
            return results

        except Exception as e:
            logger.error(f"Erro crítico no retreinamento: {e}")
            return {"status": "error", "reason": str(e)}

    def _prepare_features(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """Cria matriz de features a partir do DataFrame OHLCV."""
        try:
            d = df.copy()
            # Retornos
            d["return"]     = d["close"].pct_change()
            d["hl_ratio"]   = (d["high"] - d["low"]) / d["close"]
            d["co_ratio"]   = (d["close"] - d["open"]) / d["open"]
            # Médias móveis normalizadas
            d["ema9_norm"]  = d["close"].ewm(span=9).mean()  / d["close"]
            d["ema21_norm"] = d["close"].ewm(span=21).mean() / d["close"]
            d["vol_norm"]   = d["volume"] / d["volume"].rolling(20).mean()
            # RSI
            delta = d["close"].diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss.replace(0, 1e-10)
            d["rsi"] = 100 - (100 / (1 + rs))
            d["rsi"] = d["rsi"] / 100.0  # normaliza 0-1
            # MACD normalizado
            ema12       = d["close"].ewm(span=12).mean()
            ema26       = d["close"].ewm(span=26).mean()
            d["macd"]   = (ema12 - ema26) / d["close"]

            cols = ["return","hl_ratio","co_ratio","ema9_norm","ema21_norm","vol_norm","rsi","macd"]
            d = d[cols].dropna()
            return d.values.astype(np.float32)
        except Exception as e:
            logger.error(f"Erro ao preparar features: {e}")
            return None

    def _build_sequences(self, features: np.ndarray, seq_len: int = 30) -> Tuple[np.ndarray, np.ndarray]:
        """Constrói sequências (X, y) para treino supervisionado."""
        X, y = [], []
        for i in range(seq_len, len(features)):
            X.append(features[i - seq_len:i])
            # Target: retorno do próximo candle (índice 0 = "return")
            y.append(features[i][0])
        return np.array(X), np.array(y)

    def load_weights(self, model, model_name: str) -> bool:
        """Carrega pesos salvos em disco se existirem."""
        path = os.path.join(self.MODEL_DIR, f"{model_name}_latest.pt")
        if os.path.exists(path):
            try:
                import torch
                model.load_state_dict(torch.load(path, map_location="cpu"))
                model.eval()
                logger.info(f"✅ Pesos carregados: {path}")
                return True
            except Exception as e:
                logger.warning(f"Não foi possível carregar pesos {path}: {e}")
        return False


# ─── Orquestrador Principal ───────────────────────────────────────────────────

class AdaptiveTrainer:
    """
    Loop de aprendizado adaptativo do ZIA TRADER.

    Ciclo padrão (configurável):
      1. Coleta métricas reais do ExecutionEngine
      2. Avalia performance (win rate, drawdown, Sharpe, PF)
      3. Ajusta parâmetros do RiskAI e Engine automaticamente
      4. Retreina modelos LSTM e Transformer com dados recentes
      5. Salva relatório e persiste no Redis
      6. Aguarda o próximo ciclo

    Uso no TradingManager:
      self.adaptive_trainer = AdaptiveTrainer(settings, execution_engine, risk_ai, ...)
      asyncio.create_task(self.adaptive_trainer.start())
    """

    def __init__(
        self,
        settings,
        execution_engine,
        trading_engine,
        exchange_connector,
        redis_cache=None
    ):
        self.settings          = settings
        self.execution_engine  = execution_engine
        self.trading_engine    = trading_engine
        self.exchange_connector= exchange_connector
        self.redis_cache       = redis_cache

        self.evaluator  = PerformanceEvaluator()
        self.optimizer  = ParameterOptimizer()
        self.retrainer  = ModelRetrainer()

        # Intervalo do ciclo em segundos (padrão: 7 dias)
        self.cycle_interval = getattr(settings, "LEARNING_CYCLE_SECONDS", 604800)
        self.retrain_epochs = getattr(settings, "RETRAIN_EPOCHS", 15)
        self.is_running     = False
        self._cycle_count   = 0
        self._last_report: Optional[Dict] = None

    async def start(self):
        """Inicia o loop de aprendizado em background."""
        self.is_running = True
        logger.info(f"🧠 AdaptiveTrainer iniciado — ciclo a cada {self.cycle_interval}s")

        # Carrega pesos salvos nos modelos na inicialização
        self._load_saved_weights()

        while self.is_running:
            await asyncio.sleep(self.cycle_interval)
            if not self.is_running:
                break
            await self.run_cycle()

    async def run_cycle(self) -> Dict:
        """
        Executa um ciclo completo de aprendizado.
        Pode ser chamado manualmente para forçar um ciclo.
        """
        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"
        logger.info(f"🔄 Iniciando ciclo de aprendizado: {cycle_id}")

        report = {
            "cycle_id":  cycle_id,
            "started_at": datetime.utcnow().isoformat(),
            "phases":    {}
        }

        # ── Fase 1: Coleta de métricas ─────────────────────────────
        try:
            trade_history = self.execution_engine.trade_history
            logger.info(f"  📊 Fase 1: {len(trade_history)} trades para análise")
            metrics = self.evaluator.evaluate(trade_history)
            report["phases"]["evaluation"] = metrics
            logger.info(
                f"  Win Rate: {metrics['win_rate']:.1%} | "
                f"PF: {metrics['profit_factor']:.2f} | "
                f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
                f"PnL: ${metrics['total_pnl']:.2f}"
            )
        except Exception as e:
            logger.error(f"  ❌ Fase 1 falhou: {e}")
            report["phases"]["evaluation"] = {"error": str(e)}
            metrics = self.evaluator._empty_metrics()

        # ── Fase 2: Ajuste de parâmetros ───────────────────────────
        try:
            current_params = {
                "MAX_RISK_PER_TRADE":        getattr(self.settings, "MAX_RISK_PER_TRADE", 0.02),
                "MIN_AI_CONFIDENCE":         getattr(self.settings, "MIN_AI_CONFIDENCE", 0.70),
                "MIN_NEWS_SENTIMENT_FOR_BUY":getattr(self.settings, "MIN_NEWS_SENTIMENT_FOR_BUY", 0.3),
                "MAX_NEWS_SENTIMENT_FOR_SELL":getattr(self.settings, "MAX_NEWS_SENTIMENT_FOR_SELL", -0.3),
            }
            new_params, adjustments = self.optimizer.optimize(metrics, current_params)

            # Aplica ajustes ao settings em tempo real
            for key, val in new_params.items():
                if hasattr(self.settings, key):
                    setattr(self.settings, key, val)

            # Propaga para o RiskAI
            if hasattr(self.trading_engine, "risk_ai"):
                self.trading_engine.risk_ai.max_risk_per_trade = new_params.get("MAX_RISK_PER_TRADE", 0.02)

            report["phases"]["parameter_optimization"] = {
                "adjustments": adjustments,
                "new_params":  new_params
            }
            for adj in adjustments:
                logger.info(f"  ⚙️  {adj}")

        except Exception as e:
            logger.error(f"  ❌ Fase 2 falhou: {e}")
            report["phases"]["parameter_optimization"] = {"error": str(e)}

        # ── Fase 3: Retreinamento dos modelos ──────────────────────
        try:
            # Busca dados históricos recentes para retreino
            symbol    = self.settings.SYMBOLS[0] if self.settings.SYMBOLS else "BTC/USDT"
            timeframe = getattr(self.settings, "TIMEFRAME", "1h")
            df = await self.exchange_connector.get_historical_data(symbol, timeframe, limit=500)

            if not df.empty:
                lstm_model        = getattr(self.trading_engine, "lstm_model", None)
                transformer_model = getattr(self.trading_engine, "transformer_model", None)

                if lstm_model and transformer_model:
                    retrain_result = await self.retrainer.retrain(
                        df, lstm_model, transformer_model, epochs=self.retrain_epochs
                    )
                    report["phases"]["retraining"] = retrain_result
                    logger.info(f"  🤖 Retreinamento: {retrain_result.get('status')}")
                else:
                    report["phases"]["retraining"] = {"status": "skipped", "reason": "modelos não encontrados no engine"}
            else:
                report["phases"]["retraining"] = {"status": "skipped", "reason": "sem dados históricos"}
        except Exception as e:
            logger.error(f"  ❌ Fase 3 falhou: {e}")
            report["phases"]["retraining"] = {"error": str(e)}

        # ── Fase 4: Persiste relatório ─────────────────────────────
        report["completed_at"] = datetime.utcnow().isoformat()
        self._last_report = report

        try:
            self._save_report_to_disk(report, cycle_id)
            if self.redis_cache:
                await self.redis_cache.save_performance(metrics)
                await self.redis_cache.set_state(f"learning:{cycle_id}", report, expire=604800)
            logger.info(f"✅ Ciclo {cycle_id} concluído e salvo.")
        except Exception as e:
            logger.error(f"  ❌ Fase 4 (persistência) falhou: {e}")

        return report

    def _save_report_to_disk(self, report: Dict, cycle_id: str):
        """Salva relatório JSON em disco para auditoria."""
        os.makedirs("learning/reports", exist_ok=True)
        path = f"learning/reports/{cycle_id}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"  📁 Relatório salvo: {path}")

    def _load_saved_weights(self):
        """Carrega pesos dos modelos salvos no último ciclo."""
        try:
            lstm_model        = getattr(self.trading_engine, "lstm_model", None)
            transformer_model = getattr(self.trading_engine, "transformer_model", None)
            if lstm_model:
                self.retrainer.load_weights(lstm_model, "lstm")
            if transformer_model:
                self.retrainer.load_weights(transformer_model, "transformer")
        except Exception as e:
            logger.warning(f"Não foi possível carregar pesos anteriores: {e}")

    def get_last_report(self) -> Optional[Dict]:
        return self._last_report

    async def stop(self):
        self.is_running = False
        logger.info("AdaptiveTrainer encerrado.")
