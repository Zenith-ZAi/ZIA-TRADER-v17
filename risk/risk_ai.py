from typing import Dict, Any, List
import pandas as pd
import numpy as np
from config.settings import settings
from utils import logger

class RiskAI:
    """Módulo de IA Avançado para Gerenciamento de Risco e Validação Cirúrgica de Ordens."""
    
    def __init__(self):
        self.max_risk_per_trade = settings.MAX_RISK_PER_TRADE
        self.daily_loss_limit = 0.05  # 5% do capital total
        self.min_volume_surge = 1.5   # Volume deve ser 1.5x a média para confirmar entrada
        self.news_impact_threshold = 0.7 # Bloqueia trades se impacto de notícia > 0.7

    def validate_order(self, order_data: Dict[str, Any], account_balance: float, market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validação Cirúrgica: Analisa Volume, Notícias e Contexto de Vela antes de autorizar.
        """
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        confidence = order_data.get("confidence", 0.0)
        
        # 1. Filtro de Notícias de Alto Impacto (Calendário Econômico)
        news_impact = market_context.get("news_impact", 0.0)
        if news_impact > self.news_impact_threshold:
            logger.warning(f"Bloqueio por Notícia de Alto Impacto para {symbol}. Impacto: {news_impact}")
            return {"valid": False, "reason": "Evento macroeconômico de alto impacto detectado."}

        # 2. Confirmação de Volume (VSA - Volume Spread Analysis)
        volume_data = market_context.get("volume_analysis", {})
        is_volume_confirmed = volume_data.get("is_confirmed", False)
        if not is_volume_confirmed and confidence < 0.9:
            logger.info(f"Volume não confirmado para {symbol}. Entrada descartada.")
            return {"valid": False, "reason": "Volume insuficiente para confirmar o movimento."}

        # 3. Validação de "Estado Cirúrgico" (Confirmação de Vela)
        candle_pattern = market_context.get("candle_pattern", "neutral")
        if action == "buy" and candle_pattern not in ["bullish_engulfing", "hammer", "strong_uptrend"]:
            return {"valid": False, "reason": f"Padrão de vela {candle_pattern} não suporta compra."}
        if action == "sell" and candle_pattern not in ["bearish_engulfing", "shooting_star", "strong_downtrend"]:
            return {"valid": False, "reason": f"Padrão de vela {candle_pattern} não suporta venda."}

        # 4. Cálculo de Risco e Tamanho de Posição
        risk_amount = account_balance * self.max_risk_per_trade
        entry_price = order_data.get("price", 0.0)
        
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}
            
        # Stop Loss e Take Profit Dinâmicos baseados na Volatilidade (ATR)
        atr = market_context.get("atr", entry_price * 0.01)
        stop_loss = entry_price - (atr * 2) if action == "buy" else entry_price + (atr * 2)
        take_profit = entry_price + (atr * 4) if action == "buy" else entry_price - (atr * 4)
        
        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "quantity": risk_amount / abs(entry_price - stop_loss),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "analysis_summary": f"Volume OK, Vela {candle_pattern} OK, Risco Calculado."
        }

    def analyze_volume_flow(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analisa o fluxo de volume para identificar anomalias e confirmações."""
        if df.empty or 'volume' not in df.columns:
            return {"is_confirmed": False, "ratio": 0.0}
            
        avg_volume = df['volume'].tail(20).mean()
        last_volume = df['volume'].iloc[-1]
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0
        
        return {
            "is_confirmed": volume_ratio >= self.min_volume_surge,
            "ratio": volume_ratio,
            "trend": "increasing" if last_volume > df['volume'].iloc[-2] else "decreasing"
        }

risk_ai = RiskAI()
