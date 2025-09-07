"""
Sistema de Monitoramento e Métricas - RoboTrader 2.0
Integra com Prometheus, Grafana e sistemas de alertas
"""

import time
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import json
import aiohttp
import psutil
from prometheus_client import Counter, Histogram, Gauge, Summary, CollectorRegistry, generate_latest
from prometheus_client.exposition import MetricsHandler
from http.server import HTTPServer
import threading

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"

@dataclass
class Alert:
    """Representa um alerta do sistema"""
    id: str
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime
    source: str
    data: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[datetime] = None

@dataclass
class MetricDefinition:
    """Define uma métrica personalizada"""
    name: str
    type: MetricType
    description: str
    labels: List[str] = field(default_factory=list)
    buckets: Optional[List[float]] = None  # Para histogramas

class RoboTraderMetrics:
    """Sistema de métricas personalizado para RoboTrader"""
    
    def __init__(self):
        self.registry = CollectorRegistry()
        self._setup_metrics()
        
    def _setup_metrics(self):
        """Configurar métricas do Prometheus"""
        
        # Métricas de trading
        self.trades_total = Counter(
            'robotrader_trades_total',
            'Total number of trades executed',
            ['symbol', 'side', 'status'],
            registry=self.registry
        )
        
        self.trade_pnl = Histogram(
            'robotrader_trade_pnl',
            'Profit and Loss per trade',
            ['symbol', 'side'],
            buckets=[-1000, -500, -100, -50, -10, 0, 10, 50, 100, 500, 1000],
            registry=self.registry
        )
        
        self.portfolio_value = Gauge(
            'robotrader_portfolio_value',
            'Current portfolio value',
            ['user_id'],
            registry=self.registry
        )
        
        self.positions_count = Gauge(
            'robotrader_positions_count',
            'Number of open positions',
            ['user_id'],
            registry=self.registry
        )
        
        # Métricas de AI/ML
        self.ai_predictions_total = Counter(
            'robotrader_ai_predictions_total',
            'Total AI predictions made',
            ['model', 'symbol'],
            registry=self.registry
        )
        
        self.ai_confidence = Histogram(
            'robotrader_ai_confidence',
            'AI model confidence scores',
            ['model', 'symbol'],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            registry=self.registry
        )
        
        self.model_training_duration = Histogram(
            'robotrader_model_training_duration_seconds',
            'Time spent training AI models',
            ['model'],
            registry=self.registry
        )
        
        # Métricas de sistema
        self.api_requests_total = Counter(
            'robotrader_api_requests_total',
            'Total API requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )
        
        self.api_request_duration = Histogram(
            'robotrader_api_request_duration_seconds',
            'API request duration',
            ['method', 'endpoint'],
            registry=self.registry
        )
        
        self.websocket_connections = Gauge(
            'robotrader_websocket_connections',
            'Active WebSocket connections',
            registry=self.registry
        )
        
        self.database_connections = Gauge(
            'robotrader_database_connections',
            'Active database connections',
            ['database'],
            registry=self.registry
        )
        
        # Métricas de mercado
        self.market_data_updates = Counter(
            'robotrader_market_data_updates_total',
            'Market data updates received',
            ['symbol', 'source'],
            registry=self.registry
        )
        
        self.market_data_latency = Histogram(
            'robotrader_market_data_latency_seconds',
            'Market data latency',
            ['symbol', 'source'],
            registry=self.registry
        )
        
        # Métricas de risco
        self.risk_violations = Counter(
            'robotrader_risk_violations_total',
            'Risk management violations',
            ['type', 'severity'],
            registry=self.registry
        )
        
        self.drawdown_current = Gauge(
            'robotrader_drawdown_current',
            'Current drawdown percentage',
            ['user_id'],
            registry=self.registry
        )
        
        # Métricas de performance
        self.cpu_usage = Gauge(
            'robotrader_cpu_usage_percent',
            'CPU usage percentage',
            registry=self.registry
        )
        
        self.memory_usage = Gauge(
            'robotrader_memory_usage_bytes',
            'Memory usage in bytes',
            registry=self.registry
        )
        
        self.disk_usage = Gauge(
            'robotrader_disk_usage_percent',
            'Disk usage percentage',
            registry=self.registry
        )

class AlertManager:
    """Gerenciador de alertas do sistema"""
    
    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.alert_rules: List[Dict] = []
        self.notification_channels: List[Dict] = []
        
    def add_alert_rule(self, rule: Dict):
        """Adicionar regra de alerta"""
        self.alert_rules.append(rule)
        
    def add_notification_channel(self, channel: Dict):
        """Adicionar canal de notificação"""
        self.notification_channels.append(channel)
        
    async def create_alert(self, alert: Alert):
        """Criar novo alerta"""
        self.alerts[alert.id] = alert
        logger.warning(f"Alert created: {alert.title} - {alert.message}")
        
        # Enviar notificações
        await self._send_notifications(alert)
        
    async def resolve_alert(self, alert_id: str):
        """Resolver alerta"""
        if alert_id in self.alerts:
            self.alerts[alert_id].resolved = True
            self.alerts[alert_id].resolved_at = datetime.utcnow()
            logger.info(f"Alert resolved: {alert_id}")
            
    async def _send_notifications(self, alert: Alert):
        """Enviar notificações para canais configurados"""
        for channel in self.notification_channels:
            try:
                if channel['type'] == 'slack':
                    await self._send_slack_notification(channel, alert)
                elif channel['type'] == 'email':
                    await self._send_email_notification(channel, alert)
                elif channel['type'] == 'webhook':
                    await self._send_webhook_notification(channel, alert)
            except Exception as e:
                logger.error(f"Failed to send notification via {channel['type']}: {e}")
                
    async def _send_slack_notification(self, channel: Dict, alert: Alert):
        """Enviar notificação para Slack"""
        webhook_url = channel.get('webhook_url')
        if not webhook_url:
            return
            
        color_map = {
            AlertLevel.INFO: "good",
            AlertLevel.WARNING: "warning", 
            AlertLevel.ERROR: "danger",
            AlertLevel.CRITICAL: "danger"
        }
        
        payload = {
            "attachments": [{
                "color": color_map.get(alert.level, "warning"),
                "title": f"RoboTrader Alert: {alert.title}",
                "text": alert.message,
                "fields": [
                    {"title": "Level", "value": alert.level.value.upper(), "short": True},
                    {"title": "Source", "value": alert.source, "short": True},
                    {"title": "Time", "value": alert.timestamp.isoformat(), "short": True}
                ]
            }]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Slack notification failed: {response.status}")
                    
    async def _send_webhook_notification(self, channel: Dict, alert: Alert):
        """Enviar notificação via webhook"""
        webhook_url = channel.get('url')
        if not webhook_url:
            return
            
        payload = {
            "alert_id": alert.id,
            "level": alert.level.value,
            "title": alert.title,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "source": alert.source,
            "data": alert.data
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status not in [200, 201, 202]:
                    logger.error(f"Webhook notification failed: {response.status}")

class PerformanceMonitor:
    """Monitor de performance do sistema"""
    
    def __init__(self, metrics: RoboTraderMetrics):
        self.metrics = metrics
        self.running = False
        
    async def start_monitoring(self):
        """Iniciar monitoramento contínuo"""
        self.running = True
        while self.running:
            try:
                await self._collect_system_metrics()
                await asyncio.sleep(30)  # Coletar a cada 30 segundos
            except Exception as e:
                logger.error(f"Error collecting system metrics: {e}")
                await asyncio.sleep(60)
                
    def stop_monitoring(self):
        """Parar monitoramento"""
        self.running = False
        
    async def _collect_system_metrics(self):
        """Coletar métricas do sistema"""
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        self.metrics.cpu_usage.set(cpu_percent)
        
        # Memória
        memory = psutil.virtual_memory()
        self.metrics.memory_usage.set(memory.used)
        
        # Disco
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        self.metrics.disk_usage.set(disk_percent)

class TradingMetricsCollector:
    """Coletor de métricas de trading"""
    
    def __init__(self, metrics: RoboTraderMetrics, alert_manager: AlertManager):
        self.metrics = metrics
        self.alert_manager = alert_manager
        
    async def record_trade(self, trade_data: Dict):
        """Registrar métricas de trade"""
        symbol = trade_data.get('symbol', 'UNKNOWN')
        side = trade_data.get('side', 'UNKNOWN')
        status = trade_data.get('status', 'UNKNOWN')
        pnl = trade_data.get('pnl', 0)
        
        # Incrementar contador de trades
        self.metrics.trades_total.labels(
            symbol=symbol,
            side=side,
            status=status
        ).inc()
        
        # Registrar P&L
        if pnl is not None:
            self.metrics.trade_pnl.labels(
                symbol=symbol,
                side=side
            ).observe(pnl)
            
        # Verificar alertas de P&L
        if pnl < -500:  # Perda significativa
            alert = Alert(
                id=f"trade_loss_{trade_data.get('id', 'unknown')}_{int(time.time())}",
                level=AlertLevel.WARNING,
                title="Significant Trade Loss",
                message=f"Trade {trade_data.get('id')} resulted in loss of ${pnl:.2f}",
                timestamp=datetime.utcnow(),
                source="trading_system",
                data=trade_data
            )
            await self.alert_manager.create_alert(alert)
            
    async def update_portfolio_metrics(self, user_id: str, portfolio_data: Dict):
        """Atualizar métricas de portfólio"""
        total_value = portfolio_data.get('total_value', 0)
        positions_count = len(portfolio_data.get('positions', []))
        drawdown = portfolio_data.get('max_drawdown', 0)
        
        self.metrics.portfolio_value.labels(user_id=user_id).set(total_value)
        self.metrics.positions_count.labels(user_id=user_id).set(positions_count)
        self.metrics.drawdown_current.labels(user_id=user_id).set(abs(drawdown) * 100)
        
        # Alertas de drawdown
        if abs(drawdown) > 0.1:  # Drawdown > 10%
            alert = Alert(
                id=f"drawdown_alert_{user_id}_{int(time.time())}",
                level=AlertLevel.ERROR,
                title="High Drawdown Alert",
                message=f"Portfolio drawdown exceeded 10%: {drawdown*100:.2f}%",
                timestamp=datetime.utcnow(),
                source="risk_management",
                data={"user_id": user_id, "drawdown": drawdown}
            )
            await self.alert_manager.create_alert(alert)

class MonitoringSystem:
    """Sistema principal de monitoramento"""
    
    def __init__(self, port: int = 8000):
        self.port = port
        self.metrics = RoboTraderMetrics()
        self.alert_manager = AlertManager()
        self.performance_monitor = PerformanceMonitor(self.metrics)
        self.trading_collector = TradingMetricsCollector(self.metrics, self.alert_manager)
        self.http_server = None
        
    def setup_alert_rules(self):
        """Configurar regras de alerta padrão"""
        rules = [
            {
                "name": "high_cpu_usage",
                "condition": "cpu_usage > 80",
                "level": AlertLevel.WARNING,
                "message": "High CPU usage detected"
            },
            {
                "name": "high_memory_usage", 
                "condition": "memory_usage > 0.9",
                "level": AlertLevel.WARNING,
                "message": "High memory usage detected"
            },
            {
                "name": "api_error_rate",
                "condition": "api_error_rate > 0.05",
                "level": AlertLevel.ERROR,
                "message": "High API error rate detected"
            }
        ]
        
        for rule in rules:
            self.alert_manager.add_alert_rule(rule)
            
    def setup_notification_channels(self, config: Dict):
        """Configurar canais de notificação"""
        if config.get('slack_webhook'):
            self.alert_manager.add_notification_channel({
                'type': 'slack',
                'webhook_url': config['slack_webhook']
            })
            
        if config.get('webhook_url'):
            self.alert_manager.add_notification_channel({
                'type': 'webhook',
                'url': config['webhook_url']
            })
            
    def start_metrics_server(self):
        """Iniciar servidor de métricas HTTP"""
        def run_server():
            handler = MetricsHandler.factory(self.metrics.registry)
            httpd = HTTPServer(('0.0.0.0', self.port), handler)
            self.http_server = httpd
            logger.info(f"Metrics server started on port {self.port}")
            httpd.serve_forever()
            
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        
    async def start(self, config: Dict = None):
        """Iniciar sistema de monitoramento"""
        logger.info("Starting RoboTrader Monitoring System...")
        
        # Configurar alertas e notificações
        self.setup_alert_rules()
        if config:
            self.setup_notification_channels(config)
            
        # Iniciar servidor de métricas
        self.start_metrics_server()
        
        # Iniciar monitoramento de performance
        await self.performance_monitor.start_monitoring()
        
    def stop(self):
        """Parar sistema de monitoramento"""
        logger.info("Stopping RoboTrader Monitoring System...")
        
        self.performance_monitor.stop_monitoring()
        
        if self.http_server:
            self.http_server.shutdown()
            
    def get_metrics_data(self) -> str:
        """Obter dados de métricas em formato Prometheus"""
        return generate_latest(self.metrics.registry).decode('utf-8')

# Exemplo de uso
async def main():
    """Exemplo de uso do sistema de monitoramento"""
    
    # Configuração
    config = {
        'slack_webhook': 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK',
        'webhook_url': 'https://your-webhook-endpoint.com/alerts'
    }
    
    # Inicializar sistema
    monitoring = MonitoringSystem(port=8000)
    
    try:
        # Iniciar monitoramento
        await monitoring.start(config)
        
        # Simular alguns eventos
        await monitoring.trading_collector.record_trade({
            'id': 'trade_001',
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'status': 'executed',
            'pnl': 150.50
        })
        
        await monitoring.trading_collector.update_portfolio_metrics('user_123', {
            'total_value': 10000.0,
            'positions': [{'symbol': 'BTC/USDT'}, {'symbol': 'ETH/USDT'}],
            'max_drawdown': -0.05
        })
        
        # Manter rodando
        while True:
            await asyncio.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        monitoring.stop()

if __name__ == "__main__":
    asyncio.run(main())

