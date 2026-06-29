from prometheus_client import Gauge, Counter

# Métricas de Trading
TRADING_PNL = Gauge("zia_trader_pnl_total", "Total PnL do ZIA Trader")
TRADING_BALANCE = Gauge("zia_trader_account_balance", "Saldo atual da conta do ZIA Trader")
TRADING_OPEN_POSITIONS = Gauge("zia_trader_open_positions", "Número de posições abertas")
TRADING_ORDER_COUNT = Counter("zia_trader_order_count", "Contador de ordens executadas")
TRADING_EXECUTION_LATENCY = Gauge("zia_trader_execution_latency_seconds", "Latência de execução de ordens em segundos")

# Métricas de IA
AI_PREDICTION_CONFIDENCE = Gauge("zia_trader_ai_prediction_confidence", "Confiança da última previsão da IA")

# Métricas do Sistema
SYSTEM_ERROR_COUNT = Counter("zia_trader_system_error_count", "Contador de erros do sistema")
SYSTEM_LOG_COUNT = Counter("zia_trader_system_log_count", "Contador de logs do sistema por nível", ["level"])
