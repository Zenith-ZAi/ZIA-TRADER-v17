from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class TradingConfig(BaseSettings):
    """Configurações de trading"""
    max_portfolio_risk: float = 0.02  # 2% risco máximo por trade
    max_position_size: float = 0.1    # 10% máximo do portfólio por posição
    base_stop_loss: float = 0.02      # 2% stop loss base
    base_take_profit: float = 0.04    # 4% take profit base
    min_confidence: float = 70.0      # Confiança mínima para trade (0-100)
    max_drawdown: float = 0.15        # 15% drawdown máximo
    consecutive_losses_limit: int = 3  # Limite de perdas consecutivas
    min_balance_for_trade: float = 10.0 # Saldo mínimo para permitir trades

    model_config = SettingsConfigDict(env_prefix="TRADING_")

class AIConfig(BaseSettings):
    """Configurações do modelo de IA"""
    sequence_length: int = 60         # Comprimento da sequência de entrada para o modelo
    lstm_units: List[int] = [128, 64, 32] # Unidades LSTM por camada
    dropout_rate: float = 0.3         # Taxa de dropout
    learning_rate: float = 0.001      # Taxa de aprendizado
    batch_size: int = 64              # Tamanho do batch
    epochs: int = 100                 # Épocas de treinamento
    validation_split: float = 0.2     # Split de validação

    model_config = SettingsConfigDict(env_prefix="AI_")

class DataConfig(BaseSettings):
    """Configurações de dados"""
    symbols: List[str] = ["BTC/USDT", "ETH/USDT"]
    timeframes: List[str] = ["1m", "5m", "1h"]
    features: List[str] = ["open", "high", "low", "close", "volume"]
    lookback_days: int = 90           # Dias de dados históricos para carregar
    retention_days: int = 30          # Dias para manter dados no banco

    model_config = SettingsConfigDict(env_prefix="DATA_")

class APIConfig(BaseSettings):
    """Configurações de APIs de corretoras"""
    exchange_name: str = "binance"    # Nome da corretora padrão (ex: binance, bybit)
    sandbox_mode: bool = True         # Modo sandbox/teste
    rate_limit: bool = True           # Habilitar rate limiting
    timeout: int = 30000              # Timeout para requisições (ms)
    retry_attempts: int = 5           # Tentativas de retry
    retry_delay: float = 1.0          # Atraso entre retries (segundos)
    data_fetch_interval_seconds: int = 60 # Frequência de busca de dados (segundos)
    api_key: Optional[str] = None     # Chave da API (carregada de env)
    api_secret: Optional[str] = None  # Secret da API (carregada de env)
    password: Optional[str] = None    # Senha/Passphrase (para algumas exchanges)

    model_config = SettingsConfigDict(env_prefix="API_")

class RiskConfig(BaseSettings):
    """Configurações de gestão de risco"""
    volatility_threshold: float = 0.05 # Limite de volatilidade para alerta
    news_impact_threshold: float = 0.7 # Limite de impacto de notícias
    correlation_threshold: float = 0.8 # Limite de correlação entre ativos
    max_exposure_ratio: float = 0.8    # Exposição máxima por ativo
    risk_free_rate: float = 0.02       # Taxa livre de risco para cálculos

    model_config = SettingsConfigDict(env_prefix="RISK_")

class LoggingConfig(BaseSettings):
    """Configurações de logging"""
    level: str = "INFO"               # Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    file: str = "logs/robotrader.log" # Caminho do arquivo de log
    format: str = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
    max_size: str = "10 MB"           # Tamanho máximo do arquivo de log antes da rotação
    retention: str = "10 days"        # Tempo de retenção dos arquivos de log

    model_config = SettingsConfigDict(env_prefix="LOGGING_")

class SecurityConfig(BaseSettings):
    """Configurações de segurança"""
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    api_rate_limit_per_minute: int = 100
    # Chave para criptografia de dados sensíveis no banco de dados
    # DEVE ser gerada de forma segura e armazenada como variável de ambiente
    data_encryption_key: str

    model_config = SettingsConfigDict(env_prefix="SECURITY_")

class Settings(BaseSettings):
    """Classe principal de configurações do aplicativo"""
    trading: TradingConfig = TradingConfig()
    ai: AIConfig = AIConfig()
    data: DataConfig = DataConfig()
    api: APIConfig = APIConfig()
    risk: RiskConfig = RiskConfig()
    logging: LoggingConfig = LoggingConfig()
    security: SecurityConfig = SecurityConfig()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Instância global de configuração
config = Settings()

# Exemplo de acesso:
# print(config.trading.min_confidence)
# print(config.api.exchange_name)



