import pandas as pd
import numpy as np
from typing import Dict, Any

class WhaleDetector:
    def __init__(self, settings, db_manager):
        self.settings = settings
        self.db_manager = db_manager
        self.account_id = "default_account" # Pode ser dinâmico em um sistema real
        self.threshold = getattr(settings, 'WHALE_ACTIVITY_THRESHOLD', 0.05)
        self.volume_threshold_multiplier = getattr(settings, 'WHALE_VOLUME_THRESHOLD_MULTIPLIER', 5.0) # Ex: 5x o volume médio

    def detect_whale_activity(self, historical_data: pd.DataFrame, current_order_flow: Dict[str, Any]) -> Dict[str, Any]:
        total_volume = current_order_flow.get('total_volume', 0)
        buys = current_order_flow.get('buys', [])
        sells = current_order_flow.get('sells', [])

        # Calcular volume médio histórico para o símbolo
        if not historical_data.empty and 'volume' in historical_data.columns:
            average_volume = historical_data['volume'].mean()
        else:
            average_volume = 0.0

        # Detectar grandes ordens baseadas no volume médio
        large_buys = [b for b in buys if b['amount'] > average_volume * self.volume_threshold_multiplier]
        large_sells = [s for s in sells if s['amount'] > average_volume * self.volume_threshold_multiplier]

        is_whale_present = len(large_buys) > 0 or len(large_sells) > 0
        sentiment = "bullish" if len(large_buys) > len(large_sells) else "bearish" if len(large_sells) > 0 else "neutral"

        if is_whale_present:
            self.db_manager.create_system_log("INFO", f"Atividade de baleia detectada para {current_order_flow.get('symbol')}. Sentimento: {sentiment}", "WhaleDetector")

        return {
            "detected": is_whale_present,
            "magnitude": (len(large_buys) + len(large_sells)) / 10.0, # Magnitude simulada
            "sentiment": sentiment,
            "large_buys_count": len(large_buys),
            "large_sells_count": len(large_sells)
        }
