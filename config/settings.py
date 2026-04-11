import os
from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    # API & Server
    PROJECT_NAME: str = "ZIA Trader"
    VERSION: str = "1.0.0"
    API_PORT: int = 8000

    # Configurações para o Whale Detector
    WHALE_VOLUME_ANOMALY_THRESHOLD: float = 2.5  # Volume 2.5x a média
    WHALE_ORDER_SIZE_THRESHOLD: float = 100000.0 # Ordem > $100k
    WHALE_VOLUME_LOOKBACK_PERIOD: int = 50 # Período para calcular volume médio
    
    # Database & Cache
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./zia_trader.db")
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
    SYMBOLS: List[str] = self.CRYPTO_PAIRS # Símbolos padrão para o TradingEngine
    TIMEFRAME: str = "1h"
    MAX_RISK_PER_TRADE: float = 0.02  # 2%
    
    # API Keys (Placeholders for environment variables)
    BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
    BINANCE_SECRET_KEY: Optional[str] = os.getenv("BINANCE_SECRET_KEY")
    POLYGON_API_KEY: Optional[str] = os.getenv("POLYGON_API_KEY")
    GNEWS_API_KEY: Optional[str] = os.getenv("GNEWS_API_KEY", "YOUR_GNEWS_API_KEY")

    class Config:
        env_file = ".env"

settings = Settings()
