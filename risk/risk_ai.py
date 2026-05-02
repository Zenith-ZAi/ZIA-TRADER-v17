from typing import Dict, Any, List
import pandas as pd
import numpy as np
from config.settings import Settings
import logging
from utils import logger
from ai.whale_detector import whale_detector

class RiskAI:
    """Módulo de IA Avançado para Gerenciamento de Risco e Validação Cirúrgica de Ordens."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.max_risk_per_trade = settings.MAX_RISK_PER_TRADE
        self.daily_loss_limit = 0.05  # 5% do capital total
        self.min_volume_surge = 1.5   # Volume deve ser 1.5x a média para confirmar entrada
        self.news_impact_threshold = 0.7 # Bloqueia trades se impacto de notícia > 0.7
        self.whale_activity_threshold = 0.5 # Bloqueia trades se magnitude de baleia > 0.5 e não for na direção do trade
        self.logger = logging.getLogger(self.__class__.__name__)

    def validate_order(self, order_data: Dict[str, Any], account_balance: float, market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validação Cirúrgica: Analisa Volume, Notícias e Contexto de Vela
        antes de autorizar.
        """
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        confidence = order_data.get("confidence", 0.0)
        historical_data = market_context.get("historical_data", pd.DataFrame())
        current_order_flow = market_context.get("current_order_flow", {})
        
        # 1. Filtro de Notícias de Alto Impacto (Calendário Econômico)
        news_impact = market_context.get("news_impact", 0.0)
        if news_impact > self.news_impact_threshold:
            self.logger.warning(
                f"Bloqueio por Notícia de Alto Impacto para {symbol}. "
                f"Impacto: {news_impact}"
            )
            return {"valid": False, "reason": "Evento macroeconômico de alto impacto detectado."}

        # 2. Filtro de Atividade de Baleia (Modo Whale)
        whale_activity = whale_detector.detect_whale_activity(historical_data, current_order_flow)
        if whale_activity["detected"] and whale_activity["magnitude"] > self.whale_activity_threshold:
            # Se a baleia estiver movendo o mercado contra a nossa previsão, bloqueia
            if (action == "buy" and whale_activity["reason"] == "Ordem grande de venda") or \
               (action == "sell" and whale_activity["reason"] == "Ordem grande de compra"):
                self.logger.warning(
                    f"""Bloqueio por Atividade de Baleia Contrária para {symbol}. "
                    f"Magnitude: {whale_activity["magnitude"]} """
                )
                return {"valid": False, "reason": "Atividade de baleia contrária detectada."}
            elif whale_activity["magnitude"] > 1.5 and confidence < 0.9:  # Aumenta confiança
                # Se for uma baleia muito grande, mas na nossa direção, aumenta a confiança
                self.logger.info(
                    f"""Atividade de Baleia Favorável detectada para {symbol}. "
                    f"Magnitude: {whale_activity["magnitude"]} """
                )
                order_data["confidence"] = min(
                    1.0, confidence + (whale_activity["magnitude"] * 0.1)
                )  # Aumenta confiança

        # 3. Confirmação de Volume (VSA - Volume Spread Analysis)
        volume_data = market_context.get("volume_analysis", {})
        is_volume_confirmed = volume_data.get("is_confirmed", False)
        if not is_volume_confirmed and confidence < 0.9:
            self.logger.info(
                f"Volume não confirmado para {symbol}. Entrada descartada."
            )
            return {"valid": False, "reason": "Volume insuficiente para confirmar o movimento."}

        # 5. Análise de Sentimento de Notícias (NOVO)
        news_sentiment = market_context.get("news_sentiment", 0.0)
        if action == "buy" and news_sentiment < self.settings.MIN_NEWS_SENTIMENT_FOR_BUY:
            self.logger.info(
                f"Sentimento de notícias ({news_sentiment:.2f}) desfavorável para compra em {symbol}."
            )
            return {"valid": False, "reason": "Sentimento de notícias desfavorável para compra."}
        if action == "sell" and news_sentiment > self.settings.MAX_NEWS_SENTIMENT_FOR_SELL:
            self.logger.info(
                f"Sentimento de notícias ({news_sentiment:.2f}) desfavorável para venda em {symbol}."
            )
            return {"valid": False, "reason": "Sentimento de notícias desfavorável para venda."}

        # 6. Validação de "Estado Cirúrgico" (Confirmação de Vela)
        candle_pattern = market_context.get("candle_pattern", "neutral")
        if action == "buy" and candle_pattern not in [
            "bullish_engulfing", "hammer", "strong_uptrend"
        ]:
            return {"valid": False, "reason": f"Padrão de vela {candle_pattern} não suporta compra."}
        if action == "sell" and candle_pattern not in [
            "bearish_engulfing", "shooting_star", "strong_downtrend"
        ]:
            return {"valid": False, "reason": f"Padrão de vela {candle_pattern} não suporta venda."}

        # 6. Cálculo de Risco e Tamanho de Posição
        risk_amount = account_balance * self.max_risk_per_trade
        entry_price = order_data.get("price", 0.0)
        
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}
            
        # Stop Loss e Take Profit Dinâmicos baseados na Volatilidade (ATR)
        atr = market_context.get("atr", entry_price * 0.01)
        stop_loss = (
            entry_price - (atr * 2) if action == "buy" else entry_price + (atr * 2)
        )
        take_profit = (
            entry_price + (atr * 4) if action == "buy" else entry_price - (atr * 4)
        )
        
        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "quantity": risk_amount / abs(entry_price - stop_loss),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "analysis_summary": (
                f"Volume OK, Vela {candle_pattern} OK, Risco Calculado."
            )
        }

    def analyze_volume_flow(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analisa o fluxo de volume para identificar anomalias e confirmações."""
        if df.empty or 'volume' not in df.columns:
            return {"is_confirmed": False, "ratio": 0.0}
            
        avg_volume = df["volume"].tail(20).mean()
        last_volume = df["volume"].iloc[-1]
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0
        
        return {
            "is_confirmed": volume_ratio >= self.min_volume_surge,
            "ratio": volume_ratio,
            "trend": (
                "increasing" if last_volume > df["volume"].iloc[-2] else "decreasing"
            )
        }


