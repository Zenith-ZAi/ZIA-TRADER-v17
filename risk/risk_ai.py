from typing import Dict, Any
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
        self.whale_activity_threshold = settings.WHALE_ACTIVITY_SNIPER_THRESHOLD
        self.logger = logging.getLogger(self.__class__.__name__)

    def validate_order(
        self,
        order_data: Dict[str, Any],
        account_balance: float,
        market_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validação Cirúrgica: Volume, Notícias e Contexto de Mercado."""
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        confidence = order_data.get("confidence", 0.0)
        historical_data = market_context.get("historical_data", pd.DataFrame())
        current_order_flow = market_context.get("current_order_flow", {})

        # 1. Filtro de Notícias de Alto Impacto
        news_impact = market_context.get("news_impact", 0.0)
        if news_impact > self.news_impact_threshold:
            self.logger.warning(
                "Bloqueio por Notícia de Alto Impacto para %s. Impacto: %s",
                symbol,
                news_impact,
            )
            return {
                "valid": False,
                "reason": "Evento macroeconômico de alto impacto detectado.",
            }

        # 2. Filtro de Atividade de Baleia
        whale_activity = market_context.get(
            "whale_activity",
            {"detected": False, "magnitude": 0.0, "reason": ""},
        )
        if (
            whale_activity["detected"]
            and whale_activity["magnitude"] > self.whale_activity_threshold
        ):
            whale_reason = whale_activity["reason"]
            whale_mag = whale_activity["magnitude"]
            if (action == "buy" and "venda" in whale_reason) or (
                action == "sell" and "compra" in whale_reason
            ):
                self.logger.warning(
                    "Bloqueio por Baleia Contrária para %s. Magnitude: %s",
                    symbol,
                    whale_mag,
                )
                return {
                    "valid": False,
                    "reason": "Atividade de baleia contrária detectada.",
                }
            elif whale_mag > 1.5 and confidence < 0.9:
                self.logger.info(
                    "Baleia Favorável para %s. Magnitude: %s", symbol, whale_mag
                )
                order_data["confidence"] = min(1.0, confidence + (whale_mag * 0.1))

        # 3. Confirmação de Volume (VSA)
        volume_analysis = self.analyze_volume_flow(historical_data)
        is_volume_confirmed = volume_analysis.get("is_confirmed", False)
        if not is_volume_confirmed and confidence < self.settings.MIN_AI_CONFIDENCE:
            self.logger.info(
                "Volume não confirmado para %s. Entrada descartada.", symbol
            )
            return {
                "valid": False,
                "reason": "Volume insuficiente para confirmar o movimento.",
            }

        # 4. Análise de Sentimento de Notícias
        news_sentiment = market_context.get("news_sentiment", 0.0)
        if (
            action == "buy"
            and news_sentiment < self.settings.MIN_NEWS_SENTIMENT_FOR_BUY
        ):
            self.logger.info(
                "Sentimento (%.2f) desfavorável para compra em %s.",
                news_sentiment,
                symbol,
            )
            return {
                "valid": False,
                "reason": "Sentimento de notícias desfavorável para compra.",
            }
        if (
            action == "sell"
            and news_sentiment > self.settings.MAX_NEWS_SENTIMENT_FOR_SELL
        ):
            self.logger.info(
                "Sentimento (%.2f) desfavorável para venda em %s.",
                news_sentiment,
                symbol,
            )
            return {
                "valid": False,
                "reason": "Sentimento de notícias desfavorável para venda.",
            }

        # 5. Validação de Confiança da IA
        if confidence < self.settings.MIN_AI_CONFIDENCE:
            self.logger.info(
                "Confiança da IA (%.2f) abaixo do mínimo para %s.", confidence, symbol
            )
            return {"valid": False, "reason": "Confiança da IA abaixo do mínimo."}

        # 6. Cálculo de Risco e Tamanho de Posição
        risk_amount = account_balance * self.max_risk_per_trade
        entry_price = order_data.get("price", 0.0)

        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}

        stop_loss_factor = 0.005
        take_profit_factor = 0.01

        if action == "buy":
            stop_loss = entry_price * (1 - stop_loss_factor)
            take_profit = entry_price * (1 + take_profit_factor)
        else:
            stop_loss = entry_price * (1 + stop_loss_factor)
            take_profit = entry_price * (1 - take_profit_factor)

        sl_distance = abs(entry_price - stop_loss)
        quantity = risk_amount / sl_distance if sl_distance > 0 else 0.01

        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "price": entry_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "analysis_summary": (
                f"Volume OK, Risco Calculado. Confiança IA: {confidence:.2f}"
            ),
        }

    def analyze_volume_flow(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analisa o fluxo de volume para identificar anomalias e confirmações."""
        if df.empty or "volume" not in df.columns:
            return {"is_confirmed": False, "ratio": 0.0}

        avg_volume = (
            df["volume"].tail(self.settings.WHALE_VOLUME_LOOKBACK_PERIOD).mean()
        )
        last_volume = df["volume"].iloc[-1]
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0

        return {
            "is_confirmed": volume_ratio >= self.settings.WHALE_VOLUME_ANOMALY_THRESHOLD,
            "ratio": volume_ratio,
            "trend": (
                "increasing"
                if last_volume > df["volume"].iloc[-2]
                else "decreasing"
            ),
        }
