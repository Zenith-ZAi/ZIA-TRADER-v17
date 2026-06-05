import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MetricsCollector:
    def __init__(self):
        self.start_time = time.time()
        self.trades_executed = 0
        self.errors_count = 0
        self.last_prediction_confidence = 0.0

    def record_trade(self, success: bool = True):
        if success:
            self.trades_executed += 1
        else:
            self.errors_count += 1

    def update_confidence(self, confidence: float):
        self.last_prediction_confidence = confidence

    def get_summary(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        return {
            "uptime_seconds": round(uptime, 2),
            "trades_executed": self.trades_executed,
            "errors_count": self.errors_count,
            "avg_confidence": round(self.last_prediction_confidence, 4),
            "health_status": "healthy" if self.errors_count < 10 else "degraded"
        }

    def check_health(self) -> str:
        return "OK" if self.errors_count < 5 else "WARNING"

metrics_collector = MetricsCollector()
