from typing import Dict, Any, List
import pandas as pd
import numpy as np
from config.settings import Settings
import logging

class RiskAI:
    """Módulo de IA Avançado para Gerenciamento de Risco e Validação Cirúrgica de Ordens."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.max_risk_per_trade = settings.MAX_RISK_PER_TRADE
        self.daily_loss_limit = settings.DAILY_LOSS_LIMIT
        self.news_impact_threshold = settings.NEWS_IMPACT_THRESHOLD
        self.whale_activity_threshold = settings.WHALE_ACTIVITY_SNIPER_THRESHOLD # Usando o threshold do sniper para baleias
        self.logger = logging.getLogger(self.__class__.__name__)

    def validate_order(self, order_data: Dict[str, Any], account_balance: float, market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validação Cirúrgica: Analisa Volume, Notícias e Contexto de Mercado
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
        # whale_detector é importado e usado diretamente no core/engine, aqui apenas validamos o contexto
        whale_activity = market_context.get("whale_activity", {"detected": False, "magnitude": 0.0, "reason": ""})
        if whale_activity["detected"] and whale_activity["magnitude"] > self.whale_activity_threshold:
            # Se a baleia estiver movendo o mercado contra a nossa previsão, bloqueia
            if (action == "buy" and "venda" in whale_activity["reason"]) or \
               (action == "sell" and "compra" in whale_activity["reason"]):
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
        volume_analysis = self.analyze_volume_flow(historical_data)
        is_volume_confirmed = volume_analysis.get("is_confirmed", False)
        if not is_volume_confirmed and confidence < self.settings.MIN_AI_CONFIDENCE:
            self.logger.info(
                f"Volume não confirmado para {symbol}. Entrada descartada."
            )
            return {"valid": False, "reason": "Volume insuficiente para confirmar o movimento."}

        # 4. Análise de Sentimento de Notícias
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

        # 5. Validação de Confiança da IA
        if confidence < self.settings.MIN_AI_CONFIDENCE:
            self.logger.info(f"Confiança da IA ({confidence:.2f}) abaixo do mínimo para {symbol}. Entrada descartada.")
            return {"valid": False, "reason": "Confiança da IA abaixo do mínimo."}

        # 6. Cálculo de Risco e Tamanho de Posição
        risk_amount = account_balance * self.max_risk_per_trade
        entry_price = order_data.get("price", 0.0)
        
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}
            
        # Stop Loss e Take Profit Dinâmicos (sem ATR ou Candle Pattern)
        # Estes valores devem vir da estratégia ou ser calculados de forma mais robusta
        # Por enquanto, usamos um placeholder simples
        stop_loss_factor = 0.005 # 0.5% do preço
        take_profit_factor = 0.01 # 1% do preço

        if action == "buy":
            stop_loss = entry_price * (1 - stop_loss_factor)
            take_profit = entry_price * (1 + take_profit_factor)
        else: # sell
            stop_loss = entry_price * (1 + stop_loss_factor)
            take_profit = entry_price * (1 - take_profit_factor)
        
        # Validação de Daily Loss Limit (simplificado)
        # Em um sistema real, isso exigiria um rastreamento persistente do PnL diário
        # if (account_balance - risk_amount) / initial_account_balance < (1 - self.daily_loss_limit):
        #     self.logger.warning("Daily loss limit reached. Blocking further trades.")
        #     return {"valid": False, "reason": "Limite de perda diária atingido."}

        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "quantity": risk_amount / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0.01, # Evitar divisão por zero
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "analysis_summary": (
                f"Volume OK, Risco Calculado. Confiança IA: {confidence:.2f}"
            )
        }

    def analyze_volume_flow(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analisa o fluxo de volume para identificar anomalias e confirmações."""
        if df.empty or 'volume' not in df.columns:
            return {"is_confirmed": False, "ratio": 0.0}
            
        avg_volume = df["volume"].tail(self.settings.WHALE_VOLUME_LOOKBACK_PERIOD).mean()
        last_volume = df["volume"].iloc[-1]
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0
        
        return {
            "is_confirmed": volume_ratio >= self.settings.WHALE_VOLUME_ANOMALY_THRESHOLD,
            "ratio": volume_ratio,
            "trend": (
                "increasing" if last_volume > df["volume"].iloc[-2] else "decreasing"
            )
        }
