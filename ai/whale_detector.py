import pandas as pd
import numpy as np
from typing import Dict, Any

class WhaleDetector:
    def __init__(self, settings):
        self.settings = settings
        self.threshold = getattr(settings, 'WHALE_ACTIVITY_THRESHOLD', 0.05)

    def detect_whale_activity(self, order_flow: Dict[str, Any]) -> Dict[str, Any]:
        total_volume = order_flow.get('total_volume', 0)
        buys = order_flow.get('buys', [])
        sells = order_flow.get('sells', [])
        
        large_buys = [b for b in buys if b['amount'] > total_volume * self.threshold]
        large_sells = [s for s in sells if s['amount'] > total_volume * self.threshold]
        
        is_whale_present = len(large_buys) > 0 or len(large_sells) > 0
        sentiment = "bullish" if len(large_buys) > len(large_sells) else "bearish" if len(large_sells) > 0 else "neutral"
        
        return {
            "whale_present": is_whale_present,
            "sentiment": sentiment,
            "large_buys_count": len(large_buys),
            "large_sells_count": len(large_sells)
        }
