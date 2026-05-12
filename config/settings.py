import os
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    # API & Server
    PROJECT_NAME: str = "ZIA Trader"
    VERSION: str = "17.0.0"
    API_PORT: int = 8000

    # Configurações para o Whale Detector
    WHALE_VOLUME_ANOMALY_THRESHOLD: float = 2.5
    WHALE_ORDER_SIZE_THRESHOLD: float = 100000.0
    WHALE_VOLUME_LOOKBACK_PERIOD: int = 50
    WHALE_VOLUME_STD_MULTIPLIER: float = 2.0
    WHALE_LARGE_ORDER_THRESHOLD_USD: float = 100000.0
    WHALE_ORDER_FLOW_LOOKBACK_SECONDS: int = 60
    WHALE_ACTIVITY_SNIPER_THRESHOLD: float = 0.7

    # Database & Cache
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./zia_trader.db",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MARKET_DATA: str = "market_data"
    KAFKA_TOPIC_SIGNALS: str = "trading_signals"

    # Configurações Multi-Mercado
    FOREX_PAIRS: List[str] = ["EUR/USD", "GBP/USD"]
    CRYPTO_PAIRS: List[str] = ["BTC/USDT", "ETH/USDT"]
    MINI_INDICE_SYMBOLS: List[str] = ["WINJ24"]
    DOLAR_SYMBOLS: List[str] = ["WDOJ24"]

    # Trading
    SYMBOLS: List[str] = ["BTC/USDT", "ETH/USDT"]
    TIMEFRAME: str = "1h"
    MAX_RISK_PER_TRADE: float = 0.02
    MIN_NEWS_SENTIMENT_FOR_BUY: float = 0.3
    MAX_NEWS_SENTIMENT_FOR_SELL: float = -0.3
    MIN_AI_CONFIDENCE: float = 0.7
    TRADING_LOOP_INTERVAL: int = 60
    ERROR_RETRY_INTERVAL: int = 300

    # Risk Management
    DAILY_LOSS_LIMIT: float = 0.05
    NEWS_IMPACT_THRESHOLD: float = 0.7

    # Exchange Connectors
    CRYPTO_EXCHANGE: str = "binance"
    FOREX_BROKER: str = "oanda"

    # Sniper Engine
    SNIPER_VOLATILITY_THRESHOLD: float = 0.02
    SNIPER_TRADE_QUANTITY: float = 0.01
    SNIPER_TIMEFRAME: str = "1m"
    SNIPER_CYCLE_INTERVAL_SECONDS: int = 1
    SNIPER_PRICE_CACHE_EXPIRE: int = 60

    # API Keys (Placeholders for environment variables)
    BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
    BINANCE_SECRET_KEY: Optional[str] = os.getenv("BINANCE_SECRET_KEY")
    BYBIT_API_KEY: Optional[str] = os.getenv("BYBIT_API_KEY")
    BYBIT_SECRET_KEY: Optional[str] = os.getenv("BYBIT_SECRET_KEY")
    POLYGON_API_KEY: Optional[str] = os.getenv("POLYGON_API_KEY")
    ALPHA_VANTAGE_API_KEY: Optional[str] = os.getenv("ALPHA_VANTAGE_API_KEY", "YOUR_ALPHA_VANTAGE_API_KEY")
    BENZINGA_API_KEY: Optional[str] = os.getenv("BENZINGA_API_KEY", "YOUR_BENZINGA_API_KEY")
    GNEWS_API_KEY: Optional[str] = os.getenv("GNEWS_API_KEY", "YOUR_GNEWS_API_KEY")

    class Config:
        env_file = ".env"


settings = Settings()
