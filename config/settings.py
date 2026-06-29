import os
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict

class Settings(BaseSettings):
    # API & Server
    PROJECT_NAME: str = "ZIA Trader"
    VERSION: str = "1.0.0"
    API_PORT: int = 8000
    
    # Database & Cache
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MARKET_DATA: str = "market_data"
    KAFKA_TOPIC_SIGNALS: str = "trading_signals"
    
    # Trading
    SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    TIMEFRAME: str = "1h"
    MAX_RISK_PER_TRADE: float = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))
    MIN_CONFIDENCE_THRESHOLD: float = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.7"))
    PRICE_CHANGE_THRESHOLD: float = float(os.getenv("PRICE_CHANGE_THRESHOLD", "0.001"))
    TRADING_LOOP_INTERVAL: int = int(os.getenv("TRADING_LOOP_INTERVAL", "5"))
    ERROR_RETRY_INTERVAL: int = int(os.getenv("ERROR_RETRY_INTERVAL", "10"))

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

    # Security Settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # Smart Money Engine Settings
    SMART_MONEY_LOOKBACK_PERIOD: int = int(os.getenv("SMART_MONEY_LOOKBACK_PERIOD", "100"))

    # Risk Engine Settings
    DAILY_LOSS_LIMIT_PERCENT: float = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.05"))
    WEEKLY_LOSS_LIMIT_PERCENT: float = float(os.getenv("WEEKLY_LOSS_LIMIT_PERCENT", "0.10"))
    MONTHLY_LOSS_LIMIT_PERCENT: float = float(os.getenv("MONTHLY_LOSS_LIMIT_PERCENT", "0.15"))
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.5")) # Fractional Kelly
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    VOLATILITY_MULTIPLIER: float = float(os.getenv("VOLATILITY_MULTIPLIER", "1.5"))
    MAX_EXPOSURE_PER_SYMBOL: float = float(os.getenv("MAX_EXPOSURE_PER_SYMBOL", "0.10")) # 10% of balance
    MAX_TOTAL_EXPOSURE: float = float(os.getenv("MAX_TOTAL_EXPOSURE", "0.30")) # 30% of balance
    CORRELATION_THRESHOLD: float = float(os.getenv("CORRELATION_THRESHOLD", "0.8")) # For correlated assets

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
    ALPHA_VANTAGE_API_KEY: Optional[str] = os.getenv("ALPHA_VANTAGE_API_KEY")
    BENZINGA_API_KEY: Optional[str] = os.getenv("BENZINGA_API_KEY")

    # Exchange Connector Settings
    BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
    BINANCE_SECRET_KEY: Optional[str] = os.getenv("BINANCE_SECRET_KEY")
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

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
