import pandas as pd
import numpy as np
from typing import Dict, Any, List
from config.settings import settings
from utils import logger

class WhaleDetector:
    """Detecta movimentos de 'baleias' e ordens institucionais (Block Trades) no mercado.
    Utiliza anomalias de volume, tamanho de ordem e desequilíbrio de fluxo para identificar grandes players.
    """
    def __init__(self):
        self.volume_std_multiplier = settings.WHALE_VOLUME_STD_MULTIPLIER # Ex: 2.0 para 2 desvios padrão
        self.large_order_threshold_usd = settings.WHALE_LARGE_ORDER_THRESHOLD_USD # Ex: 100_000 USD
        self.order_flow_lookback_seconds = settings.WHALE_ORDER_FLOW_LOOKBACK_SECONDS # Ex: 60 segundos

    def detect_whale_activity(self, historical_data: pd.DataFrame, current_order_flow: Dict[str, Any]) -> Dict[str, Any]:
        """Analisa dados históricos e fluxo de ordens atual para detectar atividade de baleias de forma mais robusta.
        
        Args:
            historical_data (pd.DataFrame): Dados OHLCV históricos (com colunas 'volume', 'close').
            current_order_flow (Dict[str, Any]): Informações do fluxo de ordens atual (ex: 'buys': [], 'sells': []).
            
        Returns:
            Dict[str, Any]: Um dicionário indicando se atividade de baleia foi detectada, a magnitude e a razão.
        """
        symbol = current_order_flow.get("symbol", "UNKNOWN")

        if historical_data.empty or 'volume' not in historical_data.columns or 'close' not in historical_data.columns:
            logger.warning(f"[{symbol}] Dados históricos insuficientes para detecção de baleias.")
            return {"detected": False, "magnitude": 0.0, "reason": "Dados históricos insuficientes."}

        # 1. Detecção de Anomalia de Volume (baseado em desvio padrão)
        # Assume que historical_data já está ordenado por tempo
        recent_volumes = historical_data['volume'].tail(settings.WHALE_VOLUME_LOOKBACK_PERIOD)
        if len(recent_volumes) < 2:
            logger.debug(f"[{symbol}] Volume histórico insuficiente para cálculo de desvio padrão.")
            mean_volume = recent_volumes.iloc[-1] if not recent_volumes.empty else 0
            std_volume = 0
        else:
            mean_volume = recent_volumes.mean()
            std_volume = recent_volumes.std()

        current_volume = current_order_flow.get('total_volume', 0)
        
        is_volume_anomaly = False
        magnitude_volume = 0.0

        if std_volume > 0 and current_volume > mean_volume + (self.volume_std_multiplier * std_volume):
            is_volume_anomaly = True
            magnitude_volume = (current_volume - mean_volume) / std_volume
            logger.info(f"[{symbol}] Anomalia de Volume detectada. Volume atual: {current_volume:.2f}, Média: {mean_volume:.2f}, Std: {std_volume:.2f}")

        # 2. Detecção de Grandes Ordens e Desequilíbrio de Fluxo
        recent_buys: List[Dict[str, Any]] = current_order_flow.get('buys', [])
        recent_sells: List[Dict[str, Any]] = current_order_flow.get('sells', [])
        current_price = historical_data['close'].iloc[-1] if not historical_data.empty else 1.0

        total_buy_value = sum(order.get('price', 0) * order.get('amount', 0) for order in recent_buys)
        total_sell_value = sum(order.get('price', 0) * order.get('amount', 0) for order in recent_sells)

        is_large_order_activity = False
        magnitude_order_flow = 0.0
        order_flow_reason = ""

        if total_buy_value >= self.large_order_threshold_usd and total_buy_value > total_sell_value * 1.5:
            is_large_order_activity = True
            magnitude_order_flow = total_buy_value / self.large_order_threshold_usd
            order_flow_reason = "Grande fluxo de compra institucional."
            logger.info(f"[{symbol}] Grande fluxo de compra detectado. Valor: {total_buy_value:.2f} USD")
        elif total_sell_value >= self.large_order_threshold_usd and total_sell_value > total_buy_value * 1.5:
            is_large_order_activity = True
            magnitude_order_flow = total_sell_value / self.large_order_threshold_usd
            order_flow_reason = "Grande fluxo de venda institucional."
            logger.info(f"[{symbol}] Grande fluxo de venda detectado. Valor: {total_sell_value:.2f} USD")

        # 3. Combinação dos Indicadores
        if is_volume_anomaly and is_large_order_activity:
            magnitude = (magnitude_volume + magnitude_order_flow) / 2
            reason = f"Anomalia de volume e {order_flow_reason.lower()}"
            logger.warning(f"[{symbol}] Atividade de Baleia FORTE detectada: {reason}")
            return {"detected": True, "magnitude": magnitude, "reason": reason}
        elif is_volume_anomaly:
            reason = "Anomalia de volume significativa."
            logger.warning(f"[{symbol}] Atividade de Baleia MODERADA detectada: {reason}")
            return {"detected": True, "magnitude": magnitude_volume, "reason": reason}
        elif is_large_order_activity:
            reason = order_flow_reason
            logger.warning(f"[{symbol}] Atividade de Baleia MODERADA detectada: {reason}")
            return {"detected": True, "magnitude": magnitude_order_flow, "reason": reason}
        
        return {"detected": False, "magnitude": 0.0, "reason": "Nenhuma atividade de baleia detectada."}

whale_detector = WhaleDetector()
