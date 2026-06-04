import time
from typing import Dict, Any
from config.settings import settings
from infra.redis_cache import redis_cache

class MetricsCollector:
    """Coletor de métricas de performance e saúde do sistema."""
    def __init__(self):
        self.start_time = time.time()
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_pnl = 0.0

    def record_trade(self, status: str, pnl: float = 0.0):
        """Registra o resultado de uma operação de trading."""
        self.total_trades += 1
        if status == "success":
            self.successful_trades += 1
            self.total_pnl += pnl
        else:
            self.failed_trades += 1
            
        # Atualiza métricas no cache Redis para visualização externa
        redis_cache.set_state("system_metrics", self.get_summary())

    def get_summary(self) -> Dict[str, Any]:
        """Gera um resumo das métricas atuais."""
        uptime = time.time() - self.start_time
        win_rate = (self.successful_trades / self.total_trades) if self.total_trades > 0 else 0.0
        
        return {
            "uptime_seconds": int(uptime),
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "failed_trades": self.failed_trades,
            "win_rate": f"{win_rate:.2%}",
            "total_pnl": f"{self.total_pnl:.2f}",
            "timestamp": time.time()
        }

    def check_health(self) -> Dict[str, Any]:
        """Verifica a saúde dos componentes do sistema."""
        # Simulação de verificação de saúde
        # Em produção, verificaríamos conexões com Redis, Kafka e Exchange
        return {
            "status": "healthy",
            "redis_connected": True,
            "kafka_connected": True,
            "exchange_connected": True,
            "timestamp": time.time()
        }

metrics_collector = MetricsCollector()
