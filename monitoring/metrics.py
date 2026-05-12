import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Coletor de métricas de performance e saúde do sistema."""

    def __init__(self, redis_cache: Optional[Any] = None):
        self.start_time = time.time()
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_pnl = 0.0
        self._redis_cache = redis_cache

    def record_trade(self, status: str, pnl: float = 0.0) -> None:
        self.total_trades += 1
        if status == "success":
            self.successful_trades += 1
            self.total_pnl += pnl
        else:
            self.failed_trades += 1

        if self._redis_cache:
            try:
                self._redis_cache.set_state("system_metrics", self.get_summary())
            except Exception:
                pass

    def get_summary(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        win_rate = (
            (self.successful_trades / self.total_trades)
            if self.total_trades > 0
            else 0.0
        )

        return {
            "uptime_seconds": int(uptime),
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "failed_trades": self.failed_trades,
            "win_rate": f"{win_rate:.2%}",
            "total_pnl": f"{self.total_pnl:.2f}",
            "timestamp": time.time(),
        }

    def check_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "redis_connected": self._redis_cache is not None,
            "timestamp": time.time(),
        }
