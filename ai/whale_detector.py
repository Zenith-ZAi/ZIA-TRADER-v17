import pandas as pd
from typing import Dict, Any
from config.settings import settings
from utils import logger

class WhaleDetector:
    """Detecta movimentos de 'baleias' e ordens institucionais (Block Trades) no mercado.
    Utiliza anomalias de volume e tamanho de ordem para identificar grandes players.
    """
    def __init__(self):
        self.volume_anomaly_threshold = settings.WHALE_VOLUME_ANOMALY_THRESHOLD
        self.order_size_threshold = settings.WHALE_ORDER_SIZE_THRESHOLD

    def detect_whale_activity(self, historical_data: pd.DataFrame, current_order_flow: Dict[str, Any]) -> Dict[str, Any]:
        """Analisa dados históricos e fluxo de ordens atual para detectar atividade de baleias.
        
        Args:
            historical_data (pd.DataFrame): Dados OHLCV históricos.
            current_order_flow (Dict[str, Any]): Informações do fluxo de ordens atual (ex: volume, tamanho da ordem).
            
        Returns:
            Dict[str, Any]: Um dicionário indicando se atividade de baleia foi detectada e a magnitude.
        """
        if historical_data.empty or 'volume' not in historical_data.columns:
            return {"detected": False, "magnitude": 0.0, "reason": "Dados históricos insuficientes."}

        # 1. Análise de Anomalia de Volume
        avg_volume = historical_data['volume'].tail(settings.WHALE_VOLUME_LOOKBACK_PERIOD).mean()
        current_volume = current_order_flow.get('volume', 0)
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        is_volume_anomaly = volume_ratio >= self.volume_anomaly_threshold
        
        # 2. Análise de Tamanho de Ordem (simulado)
        order_size = current_order_flow.get('order_size', 0)
        is_large_order = order_size >= self.order_size_threshold

        if is_volume_anomaly and is_large_order:
            magnitude = (volume_ratio + (order_size / self.order_size_threshold)) / 2
            logger.info(f"Atividade de Baleia detectada! Volume Ratio: {volume_ratio:.2f}, Order Size: {order_size:.2f}")
            return {"detected": True, "magnitude": magnitude, "reason": "Anomalia de volume e ordem grande."}
        elif is_volume_anomaly:
            logger.info(f"Anomalia de Volume detectada. Volume Ratio: {volume_ratio:.2f}")
            return {"detected": True, "magnitude": volume_ratio, "reason": "Anomalia de volume."}
        elif is_large_order:
            logger.info(f"Ordem Grande detectada. Order Size: {order_size:.2f}")
            return {"detected": True, "magnitude": order_size / self.order_size_threshold, "reason": "Ordem grande."}
        
        return {"detected": False, "magnitude": 0.0, "reason": "Nenhuma atividade de baleia detectada."}

whale_detector = WhaleDetector()
