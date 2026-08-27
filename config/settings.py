import os

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict


def _env_value(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


class Settings(BaseSettings):
    # API & Server
    PROJECT_NAME: str = "ZIA Trader"
    VERSION: str = "1.1.0"
    API_PORT: int = int(os.getenv("API_PORT", os.getenv("PORT", "8000")))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    AUTO_START_ENGINES: bool = os.getenv("AUTO_START_ENGINES", "false").lower() == "true"
    ORDER_MANAGER_MODE: str = os.getenv("ORDER_MANAGER_MODE", "manual")
    ORDER_CONFIRMATION_REQUIRED: bool = os.getenv("ORDER_CONFIRMATION_REQUIRED", "true").lower() == "true"
    MANUAL_TRADING_ENABLED: bool = os.getenv("MANUAL_TRADING_ENABLED", "false").lower() == "true"
    AUTONOMOUS_TRADING_ENABLED: bool = os.getenv("AUTONOMOUS_TRADING_ENABLED", "false").lower() == "true"
    SHADOW_MODE_ENABLED: bool = os.getenv("SHADOW_MODE_ENABLED", "true").lower() == "true"
    LIVE_TRADING_ENABLED: bool = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
    LIVE_MODE: bool = os.getenv("LIVE_MODE", "false").lower() == "true"
    LIVE_KILL_SWITCH: bool = os.getenv("LIVE_KILL_SWITCH", "false").lower() == "true"
    NEURAL_MODELS_ENABLED: bool = os.getenv("NEURAL_MODELS_ENABLED", "false").lower() == "true"
    DEMO_AUTH_ENABLED: bool = os.getenv("DEMO_AUTH_ENABLED", "true").lower() == "true"
    DEMO_USER_PASSWORD: str = os.getenv("DEMO_USER_PASSWORD", "password")
    DEMO_ADMIN_PASSWORD: str = os.getenv("DEMO_ADMIN_PASSWORD", "admin")
    AUTH_MODE: str = os.getenv("AUTH_MODE", "demo")
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "")
    AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "")
    
    # Database & Cache
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REQUIRE_PERSISTENT_DATABASE: bool = os.getenv("REQUIRE_PERSISTENT_DATABASE", "false").lower() == "true"
    REQUIRE_PERSISTENT_REDIS: bool = os.getenv("REQUIRE_PERSISTENT_REDIS", "false").lower() == "true"
    
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MARKET_DATA: str = "market_data"
    KAFKA_TOPIC_SIGNALS: str = "trading_signals"
    
    # Trading
    SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    TIMEFRAME: str = "1h"
    MAX_RISK_PER_TRADE: float = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0.02"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))
    ALLOW_SHORT: bool = os.getenv("ALLOW_SHORT", "false").lower() == "true"
    MIN_CONFIDENCE_THRESHOLD: float = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.7"))
    PRICE_CHANGE_THRESHOLD: float = float(os.getenv("PRICE_CHANGE_THRESHOLD", "0.001"))
    TRADING_LOOP_INTERVAL: int = int(os.getenv("TRADING_LOOP_INTERVAL", "5"))
    ERROR_RETRY_INTERVAL: int = int(os.getenv("ERROR_RETRY_INTERVAL", "10"))
    ANALYSIS_TIMEFRAMES: str = os.getenv("ANALYSIS_TIMEFRAMES", "1m,5m,1h")
    MULTI_TIMEFRAME_ENABLED: bool = os.getenv("MULTI_TIMEFRAME_ENABLED", "false").lower() == "true"
    MULTI_TIMEFRAME_MIN_CONFIRMATIONS: int = int(os.getenv("MULTI_TIMEFRAME_MIN_CONFIRMATIONS", "2"))

    # AI Model Settings
    TRANSFORMER_INPUT_DIM: int = int(os.getenv("TRANSFORMER_INPUT_DIM", "10"))
    TRANSFORMER_D_MODEL: int = int(os.getenv("TRANSFORMER_D_MODEL", "64"))
    TRANSFORMER_NHEAD: int = int(os.getenv("TRANSFORMER_NHEAD", "4"))
    TRANSFORMER_NUM_ENCODER_LAYERS: int = int(os.getenv("TRANSFORMER_NUM_ENCODER_LAYERS", "2"))
    TRANSFORMER_SEQ_LEN: int = int(os.getenv("TRANSFORMER_SEQ_LEN", "30"))

    LSTM_INPUT_DIM: int = int(os.getenv("LSTM_INPUT_DIM", "10"))
    LSTM_HIDDEN_DIM: int = int(os.getenv("LSTM_HIDDEN_DIM", "128"))
    LSTM_NUM_LAYERS: int = int(os.getenv("LSTM_NUM_LAYERS", "2"))
    LSTM_OUTPUT_DIM: int = int(os.getenv("LSTM_OUTPUT_DIM", "1"))
    LSTM_SEQ_LEN: int = int(os.getenv("LSTM_SEQ_LEN", "30"))
    TRANSFORMER_WEIGHTS_PATH: str = os.getenv("TRANSFORMER_WEIGHTS_PATH", "models/transformer.pt")
    LSTM_WEIGHTS_PATH: str = os.getenv("LSTM_WEIGHTS_PATH", "models/lstm.pt")

    # Security Settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    CORS_ALLOWED_ORIGINS: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
    CORS_ALLOW_CREDENTIALS: bool = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"

    # Smart Money Engine Settings
    SMART_MONEY_LOOKBACK_PERIOD: int = int(os.getenv("SMART_MONEY_LOOKBACK_PERIOD", "100"))

    # Risk Engine Settings
    DAILY_LOSS_LIMIT_PERCENT: float = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.05"))
    WEEKLY_LOSS_LIMIT_PERCENT: float = float(os.getenv("WEEKLY_LOSS_LIMIT_PERCENT", "0.10"))
    MONTHLY_LOSS_LIMIT_PERCENT: float = float(os.getenv("MONTHLY_LOSS_LIMIT_PERCENT", "0.15"))
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.5")) # Fractional Kelly legado
    ADAPTIVE_KELLY_ENABLED: bool = os.getenv("ADAPTIVE_KELLY_ENABLED", "true").lower() == "true"
    ADAPTIVE_KELLY_FRACTION: float = float(os.getenv("ADAPTIVE_KELLY_FRACTION", "0.25"))
    KELLY_TARGET_VOLATILITY: float = float(os.getenv("KELLY_TARGET_VOLATILITY", "0.02"))
    KELLY_MAX_RISK_FRACTION: float = float(os.getenv("KELLY_MAX_RISK_FRACTION", "0.02"))
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    VOLATILITY_MULTIPLIER: float = float(os.getenv("VOLATILITY_MULTIPLIER", "1.5"))
    MAX_EXPOSURE_PER_SYMBOL: float = float(os.getenv("MAX_EXPOSURE_PER_SYMBOL", "0.10")) # 10% of balance
    MAX_TOTAL_EXPOSURE: float = float(os.getenv("MAX_TOTAL_EXPOSURE", "0.30")) # 30% of balance
    CORRELATION_THRESHOLD: float = float(os.getenv("CORRELATION_THRESHOLD", "0.8")) # For correlated assets
    PORTFOLIO_LOW_CORRELATION_THRESHOLD: float = float(os.getenv("PORTFOLIO_LOW_CORRELATION_THRESHOLD", "0.30"))
    PORTFOLIO_MAX_WEIGHT: float = float(os.getenv("PORTFOLIO_MAX_WEIGHT", "1.0"))
    CIRCUIT_BREAKER_ENABLED: bool = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"
    CIRCUIT_BREAKER_MAX_DRAWDOWN_PERCENT: float = float(os.getenv("CIRCUIT_BREAKER_MAX_DRAWDOWN_PERCENT", "0.15"))
    EMERGENCY_EXIT_ENABLED: bool = os.getenv("EMERGENCY_EXIT_ENABLED", "false").lower() == "true"
    EMERGENCY_EXIT_ON_NEWS_SHOCK: bool = os.getenv("EMERGENCY_EXIT_ON_NEWS_SHOCK", "false").lower() == "true"
    EMERGENCY_EXIT_ON_EVENT: bool = os.getenv("EMERGENCY_EXIT_ON_EVENT", "false").lower() == "true"
    REDIS_REQUIRED_FOR_AUTONOMOUS: bool = os.getenv("REDIS_REQUIRED_FOR_AUTONOMOUS", "true").lower() == "true"

    # Observability Settings
    PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "8001"))
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "zia-trader")

    # Kafka Topics
    KAFKA_TOPIC_TRADING_SIGNALS: str = "trading_signals"
    KAFKA_TOPIC_ORDER_EXECUTIONS: str = "order_executions"
    KAFKA_TOPIC_PNL_UPDATES: str = "pnl_updates"
    KAFKA_TOPIC_RISK_ALERTS: str = "risk_alerts"

    # Trading Symbols (for convenience, can be dynamic)
    TRADING_SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    # News Processor Settings (if applicable)
    ALPHA_VANTAGE_API_KEY: Optional[str] = _env_value("ALPHA_VANTAGE_API_KEY", "Alphavantage_API_KEY")
    BENZINGA_API_KEY: Optional[str] = _env_value("BENZINGA_API_KEY")
    MARKETAUX_API_KEY: Optional[str] = _env_value("MARKETAUX_API_KEY", "Marketaux_API_KEY")
    FINNHUB_API_KEY: Optional[str] = _env_value("FINNHUB_API_KEY", "Finnhub_API_KEY")
    TWELVE_DATA_API_KEY: Optional[str] = _env_value("TWELVE_DATA_API_KEY", "Twelvedata_API_KEY")

    # Exchange Connector Settings
    MARKET_ADAPTER: str = os.getenv("MARKET_ADAPTER", "binance")
    MARKET_TYPE: str = os.getenv("MARKET_TYPE", "spot")
    CCXT_EXCHANGE_ID: str = os.getenv("CCXT_EXCHANGE_ID", "binance")
    YAHOO_FINANCE_BASE_URL: str = os.getenv("YAHOO_FINANCE_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart")
    FOREX_MODE: str = os.getenv("FOREX_MODE", "paper")
    FOREX_PAPER_SPREAD: float = float(os.getenv("FOREX_PAPER_SPREAD", "0.0001"))
    FOREX_TICK_SIZE: float = float(os.getenv("FOREX_TICK_SIZE", "0.00001"))
    BINANCE_MODE: str = os.getenv("BINANCE_MODE") or ("demo" if os.getenv("ENVIRONMENT", "").lower() == "demo" else "simulated")
    BINANCE_DEMO_BASE_URL: Optional[str] = os.getenv("BINANCE_DEMO_BASE_URL")
    BINANCE_SPOT_BASE_URL: Optional[str] = os.getenv("BINANCE_SPOT_BASE_URL")
    BINANCE_BASE_URL_DEMO: str = os.getenv("BINANCE_BASE_URL_DEMO") or BINANCE_DEMO_BASE_URL or "https://demo-api.binance.com/api"
    BINANCE_BASE_URL_TESTNET: str = os.getenv("BINANCE_BASE_URL_TESTNET") or BINANCE_SPOT_BASE_URL or "https://testnet.binance.vision/api"
    BINANCE_BASE_URL: str = os.getenv(
        "BINANCE_BASE_URL"
    ) or (BINANCE_BASE_URL_DEMO if BINANCE_MODE.lower() == "demo" else BINANCE_BASE_URL_TESTNET)
    BINANCE_LIVE_BASE_URL: str = os.getenv("BINANCE_LIVE_BASE_URL", "https://api.binance.com/api")
    BINANCE_PUBLIC_BASE_URL: str = os.getenv("BINANCE_PUBLIC_BASE_URL", "https://data-api.binance.vision")
    BINANCE_DEMO_API_KEY: Optional[str] = os.getenv("BINANCE_DEMO_API_KEY")
    BINANCE_DEMO_SECRET_KEY: Optional[str] = os.getenv("BINANCE_DEMO_SECRET_KEY")
    BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY") or BINANCE_DEMO_API_KEY
    BINANCE_SECRET_KEY: Optional[str] = os.getenv("BINANCE_SECRET_KEY") or BINANCE_DEMO_SECRET_KEY
    BINANCE_TIMEOUT_SECONDS: float = float(os.getenv("BINANCE_TIMEOUT_SECONDS", "10"))
    BINANCE_RECV_WINDOW_MS: int = int(os.getenv("BINANCE_RECV_WINDOW_MS", "5000"))
    BINANCE_PRELOAD_EXCHANGE_INFO: bool = os.getenv("BINANCE_PRELOAD_EXCHANGE_INFO", "false").lower() in {"1", "true", "yes"}
    POLYGON_API_KEY: Optional[str] = os.getenv("POLYGON_API_KEY")

    # Whale Detector Settings
    WHALE_ACTIVITY_THRESHOLD: float = float(os.getenv("WHALE_ACTIVITY_THRESHOLD", "0.05"))
    WHALE_VOLUME_THRESHOLD_MULTIPLIER: float = float(os.getenv("WHALE_VOLUME_THRESHOLD_MULTIPLIER", "5.0"))
    WHALE_ACTIVITY_SNIPER_THRESHOLD: float = float(os.getenv("WHALE_ACTIVITY_SNIPER_THRESHOLD", "0.8")) # Threshold para o Sniper Engine

    # Sniper Engine Settings
    SNIPER_VOLATILITY_THRESHOLD: float = float(os.getenv("SNIPER_VOLATILITY_THRESHOLD", "0.02"))
    SNIPER_TIMEFRAME: str = os.getenv("SNIPER_TIMEFRAME", "1m")
    SNIPER_TRADE_QUANTITY: float = float(os.getenv("SNIPER_TRADE_QUANTITY", "0.001"))
    SNIPER_PRICE_CACHE_EXPIRE: int = int(os.getenv("SNIPER_PRICE_CACHE_EXPIRE", "60"))
    SNIPER_CYCLE_INTERVAL_SECONDS: int = int(os.getenv("SNIPER_CYCLE_INTERVAL_SECONDS", "1"))
    SNIPER_ENABLED: bool = os.getenv("SNIPER_ENABLED", "false").lower() == "true"

    # Docker Compose settings (if applicable)
    DOCKER_COMPOSE_PROJECT_NAME: str = os.getenv("DOCKER_COMPOSE_PROJECT_NAME", "zia-trader")

    # Feature Engineering Settings
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    MACD_FAST_PERIOD: int = int(os.getenv("MACD_FAST_PERIOD", "12"))
    MACD_SLOW_PERIOD: int = int(os.getenv("MACD_SLOW_PERIOD", "26"))
    MACD_SIGNAL_PERIOD: int = int(os.getenv("MACD_SIGNAL_PERIOD", "9"))
    ATR_FE_PERIOD: int = int(os.getenv("ATR_FE_PERIOD", "14"))
    VWAP_PERIOD: int = int(os.getenv("VWAP_PERIOD", "20"))
    OBV_PERIOD: int = int(os.getenv("OBV_PERIOD", "1"))

    # Ensemble Predictor Settings
    ENSEMBLE_MODEL_DIR: str = os.getenv("ENSEMBLE_MODEL_DIR", "models")
    BACKTEST_USE_ENSEMBLE: bool = os.getenv("BACKTEST_USE_ENSEMBLE", "false").lower() == "true"
    ENSEMBLE_WEIGHTS: Dict[str, float] = {
        "transformer": 0.4,
        "lstm": 0.3,
        "xgboost": 0.2,
        "random_forest": 0.1
    }

    # Smart Money Engine Settings
    BOS_COC_LOOKBACK: int = int(os.getenv("BOS_COC_LOOKBACK", "50"))
    OB_FVG_LOOKBACK: int = int(os.getenv("OB_FVG_LOOKBACK", "100"))
    LIQUIDITY_SWEEP_THRESHOLD: float = float(os.getenv("LIQUIDITY_SWEEP_THRESHOLD", "0.005"))
    PREMIUM_DISCOUNT_ZONE_THRESHOLD: float = float(os.getenv("PREMIUM_DISCOUNT_ZONE_THRESHOLD", "0.5"))

    # SQLite Fallback (if using SQLite for local development/testing)
    SQLITE_FALLBACK_ENABLED: bool = bool(os.getenv("SQLITE_FALLBACK_ENABLED", "True").lower() == "true")

    # API Rate Limiting
    API_RATE_LIMIT: int = int(os.getenv("API_RATE_LIMIT", "100")) # requests per interval
    API_RATE_LIMIT_INTERVAL: int = int(os.getenv("API_RATE_LIMIT_INTERVAL", "60")) # seconds
    API_RATE_LIMIT_BY_IP: int = int(os.getenv("API_RATE_LIMIT_BY_IP", "100"))
    API_RATE_LIMIT_BY_USER: int = int(os.getenv("API_RATE_LIMIT_BY_USER", "100"))

    # Pullback LTA/LTB / softskill em três camadas
    PULLBACK_STRATEGY_ENABLED: bool = os.getenv("PULLBACK_STRATEGY_ENABLED", "true").lower() == "true"
    PULLBACK_EMA_PERIOD: int = int(os.getenv("PULLBACK_EMA_PERIOD", "200"))
    PULLBACK_RSI_PERIOD: int = int(os.getenv("PULLBACK_RSI_PERIOD", "14"))
    PULLBACK_ATR_PERIOD: int = int(os.getenv("PULLBACK_ATR_PERIOD", "14"))
    PULLBACK_VOLUME_PERIOD: int = int(os.getenv("PULLBACK_VOLUME_PERIOD", "20"))
    PULLBACK_TOUCH_TOLERANCE: float = float(os.getenv("PULLBACK_TOUCH_TOLERANCE", "0.003"))
    PULLBACK_EXHAUSTION_VOLUME_RATIO: float = float(os.getenv("PULLBACK_EXHAUSTION_VOLUME_RATIO", "0.80"))
    PULLBACK_TRIGGER_VOLUME_RATIO: float = float(os.getenv("PULLBACK_TRIGGER_VOLUME_RATIO", "1.30"))
    PULLBACK_STOP_ATR_MULTIPLE: float = float(os.getenv("PULLBACK_STOP_ATR_MULTIPLE", "1.5"))
    PULLBACK_TARGET_ATR_MULTIPLE: float = float(os.getenv("PULLBACK_TARGET_ATR_MULTIPLE", "2.0"))
    PULLBACK_BREAKEVEN_ATR_TRIGGER: float = float(os.getenv("PULLBACK_BREAKEVEN_ATR_TRIGGER", "0.5"))
    ECONOMIC_EVENTS_FILE: str = os.getenv("ECONOMIC_EVENTS_FILE", "data/economic_events.json")
    EVENT_BLOCK_BEFORE_SECONDS: int = int(os.getenv("EVENT_BLOCK_BEFORE_SECONDS", "60"))
    EVENT_BLOCK_AFTER_SECONDS: int = int(os.getenv("EVENT_BLOCK_AFTER_SECONDS", "300"))
    MICROSTRUCTURE_GATE_ENABLED: bool = os.getenv("MICROSTRUCTURE_GATE_ENABLED", "true").lower() == "true"
    MAX_SPREAD_BPS: float = float(os.getenv("MAX_SPREAD_BPS", "30"))
    MAX_ESTIMATED_SLIPPAGE_BPS: float = float(os.getenv("MAX_ESTIMATED_SLIPPAGE_BPS", "20"))
    MIN_REWARD_RISK_RATIO: float = float(os.getenv("MIN_REWARD_RISK_RATIO", "1.2"))
    COST_AWARE_EXECUTION_ENABLED: bool = os.getenv("COST_AWARE_EXECUTION_ENABLED", "true").lower() == "true"
    MAX_BOOK_IMPACT: float = float(os.getenv("MAX_BOOK_IMPACT", "0.10"))
    ORDER_FLOW_RATIO_THRESHOLD: float = float(os.getenv("ORDER_FLOW_RATIO_THRESHOLD", "2.0"))
    ORDER_FLOW_CONFIRMATION_REQUIRED: bool = os.getenv("ORDER_FLOW_CONFIRMATION_REQUIRED", "true").lower() == "true"
    RECONCILIATION_INTERVAL_SECONDS: int = int(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "30"))
    RECONCILIATION_MAX_ATTEMPTS: int = int(os.getenv("RECONCILIATION_MAX_ATTEMPTS", "3"))
    RECONCILIATION_BASE_DELAY_SECONDS: float = float(os.getenv("RECONCILIATION_BASE_DELAY_SECONDS", "0.25"))
    RECONCILIATION_MAX_DELAY_SECONDS: float = float(os.getenv("RECONCILIATION_MAX_DELAY_SECONDS", "4.0"))
    DECISION_LOCK_TTL_SECONDS: int = int(os.getenv("DECISION_LOCK_TTL_SECONDS", "30"))
    DECISION_LOCK_RENEW_SECONDS: int = int(os.getenv("DECISION_LOCK_RENEW_SECONDS", "10"))
    OCO_ENABLED: bool = os.getenv("OCO_ENABLED", "true").lower() == "true"
    OCO_TIMEOUT_SECONDS: float = float(os.getenv("OCO_TIMEOUT_SECONDS", "5"))
    SIMULATED_ORDER_FLOW_BIAS: str = os.getenv("SIMULATED_ORDER_FLOW_BIAS", "neutral")
    SIMULATED_ORDER_FLOW_RATIO: float = float(os.getenv("SIMULATED_ORDER_FLOW_RATIO", "2.2"))

    # Fricção de execução para Sandbox/backtest; não ativa produção por padrão
    FRICTION_ENABLED: bool = os.getenv("FRICTION_ENABLED", "false").lower() == "true"
    FRICTION_SLEEP_ENABLED: bool = os.getenv("FRICTION_SLEEP_ENABLED", "false").lower() == "true"
    FRICTION_MIN_LATENCY_MS: float = float(os.getenv("FRICTION_MIN_LATENCY_MS", "150"))
    FRICTION_MAX_LATENCY_MS: float = float(os.getenv("FRICTION_MAX_LATENCY_MS", "500"))
    FRICTION_MIN_SLIPPAGE_TICKS: float = float(os.getenv("FRICTION_MIN_SLIPPAGE_TICKS", "0.5"))
    FRICTION_MAX_SLIPPAGE_TICKS: float = float(os.getenv("FRICTION_MAX_SLIPPAGE_TICKS", "2.0"))
    FRICTION_COMMISSION_RATE: float = float(os.getenv("FRICTION_COMMISSION_RATE", "0.0005"))
    FRICTION_SPREAD_PRICE: float = float(os.getenv("FRICTION_SPREAD_PRICE", "0.0"))
    FRICTION_TICK_SIZE: float = float(os.getenv("FRICTION_TICK_SIZE", "0.01"))
    FRICTION_SEED: int = int(os.getenv("FRICTION_SEED", "42"))

    # Backtest and stress validation
    BACKTEST_INITIAL_CAPITAL: float = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "10000"))
    BACKTEST_WARMUP_BARS: int = int(os.getenv("BACKTEST_WARMUP_BARS", "0"))
    BACKTEST_FEE_RATE: float = float(os.getenv("BACKTEST_FEE_RATE", "0.001"))
    BACKTEST_STOP_LOSS_PCT: float = float(os.getenv("BACKTEST_STOP_LOSS_PCT", "0.02"))
    BACKTEST_TAKE_PROFIT_PCT: float = float(os.getenv("BACKTEST_TAKE_PROFIT_PCT", "0.05"))
    BACKTEST_MAX_VOLATILITY: float = float(os.getenv("BACKTEST_MAX_VOLATILITY", "0.08"))
    RISK_FREE_RATE_ANNUAL: float = float(os.getenv("RISK_FREE_RATE_ANNUAL", "0.0"))
    METRICS_PERIODS_PER_YEAR: int = int(os.getenv("METRICS_PERIODS_PER_YEAR", "252"))
    OPTIMIZER_MAX_EVALUATIONS: int = int(os.getenv("OPTIMIZER_MAX_EVALUATIONS", "32"))
    OPTIMIZER_MAX_SECONDS: float = float(os.getenv("OPTIMIZER_MAX_SECONDS", "540"))
    OPTIMIZER_VALIDATION_FRACTION: float = float(os.getenv("OPTIMIZER_VALIDATION_FRACTION", "0.30"))
    OPTIMIZER_MIN_TRADES: int = int(os.getenv("OPTIMIZER_MIN_TRADES", "3"))
    OPTIMIZER_REOPTIMIZE_EVERY: int = int(os.getenv("OPTIMIZER_REOPTIMIZE_EVERY", "50"))

    # Memória histórica de padrões: somente padrões encerrados e rotulados; desativada por padrão
    PATTERN_MEMORY_ENABLED: bool = os.getenv("PATTERN_MEMORY_ENABLED", "false").lower() == "true"
    PATTERN_MEMORY_REQUIRE_PROFITABLE: bool = os.getenv("PATTERN_MEMORY_REQUIRE_PROFITABLE", "true").lower() == "true"
    PATTERN_MEMORY_MIN_OUTCOME_ATR: float = float(os.getenv("PATTERN_MEMORY_MIN_OUTCOME_ATR", "2.0"))
    PATTERN_MEMORY_MAX_DISTANCE: float = float(os.getenv("PATTERN_MEMORY_MAX_DISTANCE", "1.25"))
    PATTERN_MEMORY_MIN_SAMPLES: int = int(os.getenv("PATTERN_MEMORY_MIN_SAMPLES", "3"))
    LEARNING_FORWARD_HORIZON_BARS: int = int(os.getenv("LEARNING_FORWARD_HORIZON_BARS", "8"))
    LEARNING_MIN_LABELED_SAMPLES: int = int(os.getenv("LEARNING_MIN_LABELED_SAMPLES", "20"))

    # News and trend providers
    NEWS_HTTP_TIMEOUT_SECONDS: float = float(os.getenv("NEWS_HTTP_TIMEOUT_SECONDS", "8"))
    HTTP_CONNECT_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_CONNECT_TIMEOUT_SECONDS", "5"))
    HTTP_READ_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_READ_TIMEOUT_SECONDS", "15"))
    HTTP_MAX_CONNECTIONS: int = int(os.getenv("HTTP_MAX_CONNECTIONS", "50"))
    HTTP_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("HTTP_MAX_KEEPALIVE_CONNECTIONS", "20"))
    HTTP_PROVIDER_CONCURRENCY: int = int(os.getenv("HTTP_PROVIDER_CONCURRENCY", "10"))
    PROVIDER_FAILURE_THRESHOLD: int = int(os.getenv("PROVIDER_FAILURE_THRESHOLD", "3"))
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS: float = float(os.getenv("PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "60"))
    QUOTE_CACHE_TTL_SECONDS: int = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "30"))
    NEWS_CACHE_TTL_SECONDS: int = int(os.getenv("NEWS_CACHE_TTL_SECONDS", "300"))
    NEWS_MAX_ARTICLES: int = int(os.getenv("NEWS_MAX_ARTICLES", "20"))
    NEWS_PROVIDER_ARTICLES: int = int(os.getenv("NEWS_PROVIDER_ARTICLES", "10"))
    NEWS_FAIL_CLOSED_FOR_ENTRY: bool = os.getenv("NEWS_FAIL_CLOSED_FOR_ENTRY", "true").lower() == "true"
    NEWS_MIN_HEALTHY_PROVIDERS: int = int(os.getenv("NEWS_MIN_HEALTHY_PROVIDERS", "1"))
    NEWS_MIN_ARTICLES_FOR_ENTRY: int = int(os.getenv("NEWS_MIN_ARTICLES_FOR_ENTRY", "1"))
    NEWS_SHOCK_SENTIMENT_THRESHOLD: float = float(os.getenv("NEWS_SHOCK_SENTIMENT_THRESHOLD", "-0.65"))
    NEWS_SHOCK_MIN_ARTICLES: int = int(os.getenv("NEWS_SHOCK_MIN_ARTICLES", "3"))
    NEWS_MAX_ARTICLE_AGE_SECONDS: int = int(os.getenv("NEWS_MAX_ARTICLE_AGE_SECONDS", "7200"))
    GDELT_BASE_URL: str = os.getenv("GDELT_BASE_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
    NEWS_RSS_URL_TEMPLATE: str = os.getenv("NEWS_RSS_URL_TEMPLATE", "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")
    COINGECKO_BASE_URL: str = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
    COINGECKO_API_KEY: Optional[str] = _env_value("COINGECKO_API_KEY")
    BENZINGA_NEWS_URL: str = os.getenv("BENZINGA_NEWS_URL", "https://api.benzinga.com/api/v2/news")
    BENZINGA_TRENDS_URL: str = os.getenv("BENZINGA_TRENDS_URL", "https://api.benzinga.com/api/v1/trending-tickers")
    NEWSAPI_API_KEY: Optional[str] = _env_value("NEWSAPI_API_KEY", "NewsApi_API_KEY")
    NEWSAPI_BASE_URL: str = os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2/everything")
    MARKETAUX_BASE_URL: str = os.getenv("MARKETAUX_BASE_URL", "https://api.marketaux.com/v1/news/all")
    FINNHUB_BASE_URL: str = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1")
    FINNHUB_NEWS_CATEGORY: str = os.getenv("FINNHUB_NEWS_CATEGORY", "crypto")
    TWELVE_DATA_BASE_URL: str = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com")
    CRYPTOPANIC_API_KEY: Optional[str] = _env_value("CRYPTOPANIC_API_KEY")
    CRYPTOPANIC_BASE_URL: str = os.getenv("CRYPTOPANIC_BASE_URL", "https://cryptopanic.com/api/GROWTH/v2/posts/")

    @field_validator(
        "ALPHA_VANTAGE_API_KEY", "BENZINGA_API_KEY", "MARKETAUX_API_KEY", "FINNHUB_API_KEY",
        "TWELVE_DATA_API_KEY", "COINGECKO_API_KEY", "NEWSAPI_API_KEY", "CRYPTOPANIC_API_KEY",
        "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET_KEY", "BINANCE_API_KEY", "BINANCE_SECRET_KEY",
        mode="before",
    )
    @classmethod
    def _strip_secret_values(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value

    model_config = ConfigDict(env_file=".env", extra="ignore")

settings = Settings()
