"""
API de Broker Melhorada com Segurança e Performance Avançadas
"""
import ccxt
import pandas as pd
import time
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Union
import os
import hashlib
import hmac
import base64
from cryptography.fernet import Fernet
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sqlite3
from threading import Lock
import websocket
import threading

from config import config
from utils import setup_logging

logger = setup_logging(__name__)

@dataclass
class OrderResult:
    """Resultado de uma ordem"""
    success: bool
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    amount: Optional[float] = None
    price: Optional[float] = None
    status: Optional[str] = None
    timestamp: Optional[int] = None
    error_message: Optional[str] = None

class SecureCredentialManager:
    """Gerenciador seguro de credenciais"""
    
    def __init__(self, key_file: str = ".crypto_key"):
        self.key_file = key_file
        self.cipher = self._get_or_create_cipher()
    
    def _get_or_create_cipher(self) -> Fernet:
        """Obtém ou cria chave de criptografia"""
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, "wb") as f:
                f.write(key)
            os.chmod(self.key_file, 0o600)  # Apenas owner pode ler
        
        return Fernet(key)
    
    def encrypt_credential(self, credential: str) -> str:
        """Criptografa credencial"""
        return self.cipher.encrypt(credential.encode()).decode()
    
    def decrypt_credential(self, encrypted_credential: str) -> str:
        """Descriptografa credencial"""
        return self.cipher.decrypt(encrypted_credential.encode()).decode()

class RateLimiter:
    """Limitador de taxa para APIs"""
    
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = Lock()
    
    def can_make_request(self) -> bool:
        """Verifica se pode fazer requisição"""
        with self.lock:
            now = time.time()
            # Remove requisições antigas
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time < self.time_window]
            
            return len(self.requests) < self.max_requests
    
    def record_request(self):
        """Registra uma requisição"""
        with self.lock:
            self.requests.append(time.time())

class MarketDataCache:
    """Cache inteligente para dados de mercado"""
    
    def __init__(self, db_path: str = "market_cache.db"):
        self.db_path = db_path
        self._init_database()
        self.lock = Lock()
    
    def _init_database(self):
        """Inicializa banco de dados SQLite"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                symbol TEXT,
                timeframe TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                cached_at INTEGER,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        """)
        
        # Índice para consultas rápidas
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_timeframe_timestamp 
            ON market_data (symbol, timeframe, timestamp)
        """)
        
        conn.commit()
        conn.close()
    
    def get_cached_data(self, symbol: str, timeframe: str, 
                       start_time: int, end_time: int) -> Optional[pd.DataFrame]:
        """Obtém dados do cache"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM market_data
                WHERE symbol = ? AND timeframe = ? 
                AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """
            
            df = pd.read_sql_query(query, conn, params=(symbol, timeframe, start_time, end_time))
            conn.close()
            
            if len(df) > 0:
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                return df
            
            return None
    
    def cache_data(self, symbol: str, timeframe: str, data: pd.DataFrame):
        """Armazena dados no cache"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            
            # Preparar dados para inserção
            data_to_insert = []
            cached_at = int(time.time() * 1000)
            
            for _, row in data.iterrows():
                data_to_insert.append((
                    symbol, timeframe, int(row["timestamp"].timestamp() * 1000),
                    row["open"], row["high"], row["low"], row["close"], row["volume"],
                    cached_at
                ))
            
            # Inserir ou substituir dados
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO market_data 
                (symbol, timeframe, timestamp, open, high, low, close, volume, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data_to_insert)
            
            conn.commit()
            conn.close()

class EnhancedBrokerAPI:
    """API de Broker melhorada com segurança e performance"""
    
    def __init__(self, exchange_name: str = None):
        self.exchange_name = exchange_name or config.api.exchange_name
        self.exchange = None
        self.is_connected = False
        self.is_sandbox = config.api.sandbox_mode
        
        # Componentes de segurança e performance
        self.credential_manager = SecureCredentialManager()
        self.rate_limiter = RateLimiter(max_requests=10, time_window=60)
        self.cache = MarketDataCache()
        
        # Configurações
        self.retry_attempts = config.api.retry_attempts
        self.retry_delay = config.api.retry_delay
        
        # Métricas de performance
        self.metrics = {
            "requests_made": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
            "avg_response_time": 0.0
        }
        
        self._initialize_exchange()
    
    def _initialize_exchange(self):
        """Inicializa conexão com exchange de forma segura"""
        try:
            if self.is_sandbox or self.exchange_name == "simulated_exchange":
                logger.warning("⚠️ Modo Sandbox ativado. Operando em modo de simulação (dados dummy).")
                self.exchange = None
                self.is_connected = False
                return
            
            # Obter credenciais criptografadas
            api_key = self._get_secure_credential(f"{self.exchange_name.upper()}_API_KEY")
            api_secret = self._get_secure_credential(f"{self.exchange_name.upper()}_API_SECRET")
            api_passphrase = self._get_secure_credential(f"{self.exchange_name.upper()}_API_PASSPHRASE")
            
            # Validação de credenciais
            if not api_key or not api_secret:
                logger.error(f"❌ Credenciais API (API_KEY ou API_SECRET) ausentes para {self.exchange_name}. Não é possível conectar.")
                self.is_connected = False
                self.exchange = None
                return

            # Configuração da exchange
            exchange_class = getattr(ccxt, self.exchange_name)
            
            config_dict = {
                "apiKey": api_key,
                "secret": api_secret,
                "timeout": config.api.timeout,
                "enableRateLimit": config.api.rate_limit,
                "sandbox": self.is_sandbox
            }
            
            if api_passphrase:
                config_dict["passphrase"] = api_passphrase
            
            self.exchange = exchange_class(config_dict)
            
            try:
                self.exchange.load_markets()
                self.is_connected = True
                logger.info(f"✅ Conectado à {self.exchange_name} {"(sandbox)" if self.is_sandbox else ""}")
            except Exception as e:
                logger.error(f"❌ Erro ao carregar mercados para {self.exchange_name}: {e}")
                self.is_connected = False
                self.exchange = None
            
        except Exception as e:
            logger.error(f"❌ Erro ao conectar com {self.exchange_name}: {e}")
            self.is_connected = False
            self.exchange = None
            self.metrics["errors"] += 1
    
    def _get_secure_credential(self, env_var: str) -> str:
        """Obtém credencial de forma segura"""
        encrypted_cred = os.getenv(env_var, "")
        if encrypted_cred:
            try:
                return self.credential_manager.decrypt_credential(encrypted_cred)
            except:
                # Se não conseguir descriptografar, assume que está em texto plano
                return encrypted_cred
        return ""
    
    async def get_market_data_async(self, symbol: str = "BTC/USDT", 
                                   timeframe: str = "1m", limit: int = 100) -> pd.DataFrame:
        """Obtém dados de mercado de forma assíncrona"""
        start_time = time.time()
        
        try:
            # Verificar rate limit
            if not self.rate_limiter.can_make_request():
                logger.warning("Rate limit atingido. Aguardando...")
                await asyncio.sleep(1)
            
            # Verificar cache primeiro
            end_time = int(time.time() * 1000)
            start_time_cache = end_time - (limit * self._timeframe_to_ms(timeframe))
            
            cached_data = self.cache.get_cached_data(symbol, timeframe, start_time_cache, end_time)
            
            if cached_data is not None and len(cached_data) >= limit * 0.8:  # 80% dos dados no cache
                self.metrics["cache_hits"] += 1
                logger.debug(f"Cache hit para {symbol} {timeframe}")
                return cached_data.tail(limit)
            
            # Buscar dados da API
            self.metrics["cache_misses"] += 1
            self.rate_limiter.record_request()
            
            if not self.exchange or not self.is_connected:
                return self._generate_dummy_data(symbol, limit, timeframe)
            
            # Fazer requisição com retry
            ohlcv_data = await self._fetch_with_retry(
                self.exchange.fetch_ohlcv, symbol, timeframe, limit=limit
            )
            
            # Converter para DataFrame
            df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            
            # Armazenar no cache
            self.cache.cache_data(symbol, timeframe, df)
            
            # Atualizar métricas
            response_time = time.time() - start_time
            self._update_response_time_metric(response_time)
            self.metrics["requests_made"] += 1
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter dados de mercado: {e}")
            self.metrics["errors"] += 1
            return self._generate_dummy_data(symbol, limit, timeframe)
    
    def get_market_data(self, symbol: str = "BTC/USDT", 
                       timeframe: str = "1m", limit: int = 100) -> pd.DataFrame:
        """Versão síncrona de get_market_data_async"""
        return asyncio.run(self.get_market_data_async(symbol, timeframe, limit))
    
    async def _fetch_with_retry(self, func, *args, **kwargs):
        """Executa função com retry automático"""
        for attempt in range(self.retry_attempts):
            try:
                return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise e
                
                wait_time = self.retry_delay * (2 ** attempt)  # Backoff exponencial
                logger.warning(f"Tentativa {attempt + 1} falhou. Aguardando {wait_time}s...")
                await asyncio.sleep(wait_time)
    
    def _timeframe_to_ms(self, timeframe: str) -> int:
        """Converte timeframe para milissegundos"""
        timeframe_ms = {
            "1m": 60 * 1000,
            "5m": 5 * 60 * 1000,
            "15m": 15 * 60 * 1000,
            "1h": 60 * 60 * 1000,
            "4h": 4 * 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000
        }
        return timeframe_ms.get(timeframe, 60 * 1000)
    
    def _update_response_time_metric(self, response_time: float):
        """Atualiza métrica de tempo de resposta"""
        if self.metrics["requests_made"] == 0:
            self.metrics["avg_response_time"] = response_time
        else:
            # Média móvel
            alpha = 0.1
            self.metrics["avg_response_time"] = (
                alpha * response_time + 
                (1 - alpha) * self.metrics["avg_response_time"]
            )
    
    async def place_order_async(self, symbol: str, order_type: str, side: str, 
                               amount: float, price: Optional[float] = None) -> OrderResult:
        """Coloca ordem de forma assíncrona e segura"""
        start_time = time.time()
        
        try:
            # Validar parâmetros
            if not self._validate_order_params(symbol, order_type, side, amount, price):
                return OrderResult(
                    success=False,
                    error_message="Parâmetros de ordem inválidos"
                )
            
            # Verificar rate limit
            if not self.rate_limiter.can_make_request():
                return OrderResult(
                    success=False,
                    error_message="Rate limit atingido"
                )
            
            self.rate_limiter.record_request()
            
            if not self.is_connected or not self.exchange:
                # Simular ordem
                return self._simulate_order(symbol, order_type, side, amount, price)
            
            # Colocar ordem real com retry
            order = await self._fetch_with_retry(
                self.exchange.create_order, symbol, order_type, side, amount, price
            )
            
            # Atualizar métricas
            response_time = time.time() - start_time
            self._update_response_time_metric(response_time)
            self.metrics["requests_made"] += 1
            
            return OrderResult(
                success=True,
                order_id=order.get("id"),
                symbol=symbol,
                side=side,
                amount=amount,
                price=price or order.get("price"),
                status=order.get("status"),
                timestamp=order.get("timestamp")
            )
            
        except Exception as e:
            logger.error(f"❌ Erro ao colocar ordem: {e}")
            self.metrics["errors"] += 1
            return OrderResult(
                success=False,
                error_message=str(e)
            )
    
    def place_order(self, symbol: str, order_type: str, side: str, 
                   amount: float, price: Optional[float] = None) -> OrderResult:
        """Versão síncrona de place_order_async"""
        return asyncio.run(self.place_order_async(symbol, order_type, side, amount, price))
    
    def _validate_order_params(self, symbol: str, order_type: str, side: str, 
                              amount: float, price: Optional[float]) -> bool:
        """Valida parâmetros da ordem"""
        if not symbol or not order_type or not side:
            return False
        
        if amount <= 0:
            return False
        
        if order_type.lower() not in ["market", "limit"]:
            return False
        
        if order_type.lower() == "limit" and price is None or price <= 0:
            return False
        
        return True
    
    async def get_account_balance(self) -> float:
        """Obtém saldo da conta"""
        if not self.is_connected or not self.exchange:
            logger.warning("⚠️ Não conectado à corretora. Retornando saldo simulado.")
            return 10000.0 # Saldo dummy para simulação
        
        try:
            balance = await self._fetch_with_retry(self.exchange.fetch_balance)
            # Retorna o saldo total em USDT ou moeda base configurada
            return balance["total"].get("USDT", 0.0) # Ajustar para a moeda base
        except Exception as e:
            logger.error(f"❌ Erro ao obter saldo da conta: {e}")
            return 0.0

    def _generate_dummy_data(self, symbol: str, limit: int, timeframe: str) -> pd.DataFrame:
        """Gera dados dummy para simulação"""
        logger.warning(f"Gerando dados dummy para {symbol} ({timeframe}) - Modo simulação")
        data = []
        now = datetime.now()
        interval_ms = self._timeframe_to_ms(timeframe)
        
        for i in range(limit):
            timestamp = now - timedelta(milliseconds=(limit - 1 - i) * interval_ms)
            open_price = 100 + np.random.rand() * 10
            close_price = open_price + (np.random.rand() - 0.5) * 2
            high_price = max(open_price, close_price) + np.random.rand()
            low_price = min(open_price, close_price) - np.random.rand()
            volume = 1000 + np.random.rand() * 500
            data.append([timestamp, open_price, high_price, low_price, close_price, volume])
            
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        return df

    def _simulate_order(self, symbol: str, order_type: str, side: str, 
                        amount: float, price: Optional[float]) -> OrderResult:
        """Simula a execução de uma ordem"""
        logger.info(f"Simulando ordem: {side.upper()} {amount} {symbol} a {price or 'MARKET'}")
        return OrderResult(
            success=True,
            order_id=f"SIM_{int(time.time() * 1000)}",
            symbol=symbol,
            side=side,
            amount=amount,
            price=price or (10000 if side == "buy" else 9900), # Preço simulado
            status="closed",
            timestamp=int(time.time() * 1000)
        )

    def get_metrics(self) -> Dict:
        """Retorna métricas de performance da API"""
        return self.metrics




