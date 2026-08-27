from prometheus_client import Gauge, Counter, Histogram

# Métricas de Trading
TRADING_PNL = Gauge("zia_trader_pnl_total", "Total PnL do ZIA Trader")
TRADING_BALANCE = Gauge("zia_trader_account_balance", "Saldo atual da conta do ZIA Trader")
TRADING_OPEN_POSITIONS = Gauge("zia_trader_open_positions", "Número de posições abertas")
TRADING_ORDER_COUNT = Counter("zia_trader_order_count", "Contador de ordens executadas")
TRADING_EXECUTION_LATENCY = Gauge("zia_trader_execution_latency_seconds", "Latência de execução de ordens em segundos")

# Métricas de IA
AI_PREDICTION_CONFIDENCE = Gauge("zia_trader_ai_prediction_confidence", "Confiança da última previsão da IA")
AI_LOCAL_DECISION_LATENCY = Histogram("zia_trader_ai_local_decision_latency_seconds", "Latência local da decisão, sem rede da exchange", buckets=(0.001, 0.003, 0.005, 0.010, 0.020, 0.050, 0.100, 0.250, 1.0))
AI_NEWS_FETCH_LATENCY = Histogram("zia_trader_ai_news_fetch_latency_seconds", "Latência de consulta e normalização de notícias", buckets=(0.010, 0.050, 0.100, 0.250, 0.500, 1.0, 3.0, 10.0))

# Métricas do Sistema
SYSTEM_ERROR_COUNT = Counter("zia_trader_system_error_count", "Contador de erros do sistema")
SYSTEM_LOG_COUNT = Counter("zia_trader_system_log_count", "Contador de logs do sistema por nível", ["level"])
RECONCILIATION_DIVERGENCE = Counter("reconciliation_divergence_total", "Divergências detectadas pela reconciliação")
KILL_SWITCH_ACTIVE = Gauge("zia_kill_switch_active", "Estado do kill switch: 1 ativo, 0 inativo")
DAILY_DRAWDOWN_RATIO = Gauge("zia_daily_drawdown_ratio", "Drawdown diário relativo")
PROVIDER_REQUESTS = Counter("zia_provider_requests_total", "Chamadas a provedores por resultado", ["provider", "status"])
