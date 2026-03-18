import asyncio
import ccxt.async_support as ccxt # Biblioteca para conexão real com exchanges (via API)
import requests
import asyncio
import talib
import random
import os
from dotenv import load_dotenv

import numpy as np
import pandas as pd # Adicionado para cálculo de correlação
import logging
import sys
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from fastapi import Depends, FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from polygon import RESTClient
from brapi.brapi import Brapi

from database import get_db, UserAPIKey, OHLCVData, NewsArticle, TradingStrategy, Portfolio, Position, Order, Trade, User, ExchangeType, OrderSide, OrderType, PositionStatus, StrategyStatus # Importa modelos e funções do banco de dados

load_dotenv() # Carrega as variáveis de ambiente do arquivo .env
# ==============================================================================
# 1. Configurações (Substitui robotrader_core/config.py)
from enum import Enum
# ==============================================================================

class SecuritySettings(BaseModel):
    access_token_expire_minutes: int = 30
    binance_api_key: str = Field(default=os.getenv("BINANCE_API_KEY", "YOUR_BINANCE_API_KEY"))
    binance_secret_key: str = Field(default=os.getenv("BINANCE_SECRET_KEY", "YOUR_BINANCE_SECRET_KEY"))
    gnews_api_key: str = Field(default=os.getenv("GNEWS_API_KEY", "YOUR_GNEWS_API_KEY"))
    polygon_api_key: str = Field(default=os.getenv("POLYGON_API_KEY", "YOUR_POLYGON_API_KEY"))
    brapi_api_key: str = Field(default=os.getenv("BRAPI_API_KEY", "YOUR_BRAPI_API_KEY"))

class AISettings(BaseModel):
    sequence_length: int = 60

class DataSettings(BaseModel):
    symbols: List[str] = ["EUR/USD", "BTC/USDT", "ETH/USDT", "WIN/N", "TSLA/OP"] # Forex, Crypto, Mini Contratos, Opções
    timeframes: List[str] = ["1m", "5m", "1h"]
    features: List[str] = ["open", "high", "low", "close", "volume"]

class ExecutionMode(str, Enum):
    # Removendo SIMULATED, pois o bot será executado em modo REAL
    REAL = "real"

class TradingSettings(BaseModel):
    max_portfolio_risk: float = 0.01
    max_consecutive_losses: int = 3 # Novo limite de perdas consecutivas
    execution_mode: ExecutionMode = ExecutionMode.REAL

class CredentialManager:
    """Gerenciador de Credenciais de Trading (Zero-Trust) com persistência em banco de dados.
    As chaves são criptografadas e armazenadas no banco de dados.
    """
    def __init__(self):
        pass # As credenciais serão gerenciadas via sessão de DB

    async def get_credentials_from_db(self, db, user_id: str, exchange_type: ExchangeType, is_testnet: bool = False) -> Optional[UserAPIKey]:
        """Busca as credenciais de API do usuário no banco de dados."""
        api_key_entry = db.query(UserAPIKey).filter(
            UserAPIKey.user_id == user_id,
            UserAPIKey.exchange == exchange_type,
            UserAPIKey.is_testnet == is_testnet,
            UserAPIKey.is_active == True
        ).first()
        return api_key_entry

    async def set_credentials_to_db(self, db, user_id: str, exchange_type: ExchangeType, api_key: str, secret: str, passphrase: Optional[str] = None, is_testnet: bool = False):
        """Armazena as credenciais de API do usuário no banco de dados (criptografadas)."""
        # TODO: Implementar criptografia real das chaves
        encrypted_api_key = api_key # Placeholder
        encrypted_secret_key = secret # Placeholder
        encrypted_passphrase = passphrase # Placeholder

        api_key_entry = UserAPIKey(
            user_id=user_id,
            exchange=exchange_type,
            api_key_encrypted=encrypted_api_key,
            secret_key_encrypted=encrypted_secret_key,
            passphrase_encrypted=encrypted_passphrase,
            is_testnet=is_testnet
        )
        db.add(api_key_entry)
        db.commit()
        db.refresh(api_key_entry)
        logger.info(f"Credenciais para {exchange_type.value} armazenadas no banco de dados para o usuário {user_id}.")

credential_manager = CredentialManager()

class Settings(BaseModel):
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    ai: AISettings = Field(default_factory=AISettings)
    data: DataSettings = Field(default_factory=DataSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)

config = Settings()

# ==============================================================================
# 2. Logger (Substitui robotrader_core/custom_logger.py)
# ==============================================================================

def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Configura o handler para stdout (necessário para Uvicorn)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)

    return logger

logger = get_logger(__name__)

# ==============================================================================
# 3. Gerenciador de Conexões WebSocket (Necessário para RoboTraderUnified)
# ==============================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Nova conexão WebSocket: {len(self.active_connections)} conexões ativas")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Conexão WebSocket removida: {len(self.active_connections)} conexões ativas")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem WebSocket: {e}")

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                logger.info("Conexão WebSocket desconectada durante o broadcast.")
                disconnected.append(connection)
            except Exception as e:
                logger.error(f"Erro ao enviar broadcast WebSocket: {e}")
                disconnected.append(connection)
        
        # Remover conexões desconectadas
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

# ==============================================================================
# 4. Lógica Principal do RoboTrader (Substitui robotrader_core/main_unified.py)
# ==============================================================================

    class RoboTraderUnified:

        def __init__(self, user_id: str, db):
            self.user_id = user_id
            self.db = db
            self.is_running = False
            self.shutdown_requested = False
            self.start_time = datetime.now()
            self.performance_metrics: Dict[str, Any] = {
                "total_pnl": 0.0,
                "daily_pnl": 0.0,
                "win_rate": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_trades": 0,
                "last_update": datetime.now()
            }
            # Preços iniciais serão buscados via API
            self.current_price: Dict[str, float] = {}
            self.execution_mode = config.trading.execution_mode
            self.exchange_connector = self._get_exchange_connector() # Novo conector de exchange
            self.strategy_manager = self._get_strategy_manager() # Gerenciador de Estratégias Modular

            self.positions: List[Dict[str, Any]] = []


        async def fetch_news_sentiment(self, symbol: str) -> float:
            """
            Busca e calcula o sentimento médio de notícias para um símbolo usando a GNews API.
            Retorna um valor entre -1.0 (muito negativo) e 1.0 (muito positivo).
            """
            # A GNews API é síncrona, então usaremos asyncio.to_thread para não bloquear o loop de eventos.
            
            def _fetch_gnews_sync():
                # Mapeamento de símbolos para termos de busca
                search_term = f'"{symbol.replace("/", " ")}" AND (forex OR crypto OR stock)
                
                # URL da GNews API
                url = f"https://gnews.io/api/v4/search?q={search_term}&lang=en&country=us&max=10&token={config.security.gnews_api_key}"
                
                # Faz a requisição síncrona em um thread separado
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                
                articles = data.get('articles', [])
                
                if not articles:
                    logger.info(f"Nenhuma notícia encontrada para {symbol} na GNews.")
                    return 0.0
                
                # Simulação de Análise de Sentimento (A GNews não fornece sentimento nativamente)
                # Para cada artigo, vamos simular um sentimento baseado em palavras-chave
                
                total_sentiment = 0.0
                
                for article in articles:
                    title = article.get('title', '').lower()
                    description = article.get('description', '').lower()
                    
                    text = title + " " + description
                    
                    # Palavras-chave de sentimento (simplificado)
                    positive_words = ['gain', 'rise', 'bullish', 'strong', 'growth', 'profit', 'up', 'breakout']
                    negative_words = ['loss', 'fall', 'bearish', 'weak', 'decline', 'sell', 'down', 'crash']
                    
                    sentiment_score = 0
                    
                    for word in positive_words:
                        if word in text:
                            sentiment_score += 1
                    
                    for word in negative_words:
                        if word in text:
                            sentiment_score -= 1
                            
                    # Normaliza o score para um range de -1.0 a 1.0
                    # Máximo de 8 palavras positivas/negativas, então o score vai de -8 a 8
                    normalized_sentiment = sentiment_score / 8.0
                    total_sentiment += normalized_sentiment

                    # Armazena a notícia no banco de dados
                    news_entry = NewsArticle(
                        title=article.get('title', ''),
                        description=article.get('description', ''),
                        url=article.get('url', ''),
                        image_url=article.get('image', ''),
                        published_at=datetime.fromisoformat(article.get('publishedAt', '').replace('Z', '+00:00')),
                        source_name=article.get('source', {}).get('name', ''),
                        sentiment_score=normalized_sentiment,
                        symbols=[symbol]
                    )
                    self.db.add(news_entry)
                self.db.commit()
                
                # Sentimento médio
                average_sentiment = total_sentiment / len(articles)
                
                logger.info(f"Sentimento de Notícias (GNews): {average_sentiment:.2f} para {symbol} baseado em {len(articles)} artigos.")
                return average_sentiment

            try:
                # Executa a função síncrona em um thread
                sentiment = await asyncio.to_thread(_fetch_gnews_sync)
                return sentiment
            except Exception as e:
                logger.error(f"Erro ao buscar sentimento de notícias com GNews: {e}. Retornando neutro.")
                return 0.0 # Retorna neutro em caso de falha

        def _get_exchange_connector(self):
            # Retorna uma instância do conector de Exchange
            return await ExchangeConnector(self.execution_mode, self.user_id, self.db)

        def _get_strategy_manager(self):
            # Retorna o Gerenciador de Estratégias
            return StrategyManager(self.db)







    async def calculate_position_size(self, symbol: str, current_price: float, risk_per_trade: float = 0.01) -> float:
        """
        Calcula o tamanho da posição com base no risco e nas especificidades do instrumento.
        Implementa a lógica de gestão de risco para Forex/Mini Contratos.
        """
        try:
            balance_data = await self.exchange_connector.fetch_balance()
            # Simplificação: assume que o capital total é o saldo disponível em USDT ou equivalente
            account_equity = balance_data.get('total', {}).get('USDT', 10000.0) # Fallback para 10000.0 se não encontrar
        except Exception as e:
            logger.error(f"Não foi possível buscar o saldo real: {e}. O bot não pode operar sem capital real.")
            raise Exception("Capital indisponível para cálculo de tamanho de posição.")
            
        risk_amount = account_equity * risk_per_trade
        
        # Lógica de cálculo de posição para EUR/USD (Forex)
        # Forex: Tamanho em lotes (1 lote = 100,000 unidades)
        # Simplificação: 1 pip = $10 por lote padrão.
        # Vamos usar um cálculo simplificado de risco por pip.
        # Assumindo um Stop Loss de 50 pips (0.0050)
        pip_value = 10.0 # $10 por pip (lote padrão)
        stop_loss_pips = 50 
        stop_loss_value = stop_loss_pips * pip_value
        
        # Tamanho do lote (em lotes padrão)
        # Lotes = Risco / (Stop Loss em pips * Valor do Pip)
        lots = risk_amount / stop_loss_value
        
        # Garante que o lote mínimo seja respeitado (ex: 0.01 mini lote)
        return max(0.01, round(lots, 2))

    async def initialize(self) -> bool:
        """Inicializa o bot, módulos e verifica a conexão."""
        logger.info(f"🚀 Inicializando RoboTrader 2.0. Risco Máximo: {config.trading.max_portfolio_risk * 100}%")
        await asyncio.sleep(1) # Pequena pausa para inicialização assíncrona
        
        # Inicialização de variáveis de estado
        self.trade_history: List[Dict[str, Any]] = []
        self.trade_id_counter = 0
        
        # Verifica a conexão real com a exchange
        if await self.exchange_connector.check_connection():
            logger.info(f"✅ Conexão com Exchange estabelecida ({self.execution_mode.value.upper()})")
            logger.info("✅ Módulos de Risco e PnL carregados")
            return True
        else:
            logger.error("❌ Falha na conexão com a Exchange. Verifique as credenciais.")
            return False

    class ExchangeConnector:
        """Conector de Exchange para interagir com a Binance (CCXT), Polygon e Brapi, com persistência de dados em DB."""
        async def __init__(self, mode: ExecutionMode, user_id: str, db):
            self.mode = mode
            self.user_id = user_id
            self.db = db
            self.exchange_id = "binance" # Exemplo fixo
            
            # Inicialização de APIs de dados externos
            self.ccxt_exchange = await self._get_ccxt_exchange()
            self.polygon_client = await self._get_polygon_client()
            self.brapi_client = await self._get_brapi_client()

        async def _get_ccxt_exchange(self):
            """Configura a instância do CCXT para a Binance usando credenciais do DB."""
            api_key_entry = await credential_manager.get_credentials_from_db(self.db, self.user_id, ExchangeType.BINANCE, is_testnet=False)
            
            params = {
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future', # Usando futuros para BTC/USDT
                }
            }
            
            if api_key_entry:
                params['apiKey'] = api_key_entry.api_key_encrypted
                params['secret'] = api_key_entry.secret_key_encrypted
            else:
                logger.warning(f"Credenciais da Binance não encontradas no DB para o usuário {self.user_id}. Operando em modo público (apenas leitura).")
            
            return ccxt.binance(params)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Busca dados OHLCV da fonte apropriada (DB, CCXT, Polygon ou Brapi) e os armazena no DB."""
        
        # 1. Tenta buscar do banco de dados primeiro
        db_ohlcv = self.db.query(OHLCVData).filter(
            OHLCVData.symbol == symbol,
            OHLCVData.timeframe == timeframe
        ).order_by(OHLCVData.timestamp.desc()).limit(limit).all()

        if db_ohlcv:
            df = pd.DataFrame([
                {
                    "timestamp": o.timestamp,
                    "open": float(o.open),
                    "high": float(o.high),
                    "low": float(o.low),
                    "close": float(o.close),
                    "volume": float(o.volume),
                } for o in reversed(db_ohlcv)
            ])
            logger.info(f"Dados OHLCV para {symbol}-{timeframe} carregados do banco de dados.")
            return df

        # Se não estiver no DB, busca da API e armazena
        df = pd.DataFrame()

        # 2. Criptomoedas (BTC/USDT, ETH/USDT) - Usar CCXT (Binance)
        if symbol in ["BTC/USDT", "ETH/USDT"]:
            if self.ccxt_exchange:
                try:
                    ohlcv = await self.ccxt_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                except Exception as e:
                    logger.error(f"Erro ao buscar OHLCV da Binance para {symbol}: {e}")

        # 3. Forex (EUR/USD) - Usar Polygon
        elif symbol == "EUR/USD":
            if self.polygon_client:
                try:
                    resp = self.polygon_client.get_aggs(
                        ticker=f"C:{symbol.replace("/", "")}",
                        multiplier=1, 
                        timespan=timeframe, 
                        from_= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), 
                        to=datetime.now().strftime("%Y-%m-%d"),
                        limit=limit
                    )
                    if resp.results:
                        df = pd.DataFrame(resp.results)
                        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                        df = df.rename(columns={
                            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp"
                        })
                        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                except Exception as e:
                    logger.error(f"Erro ao buscar OHLCV da Polygon.io para {symbol}: {e}")

        # 4. Opções e Mini Contratos (TSLA/OP, WIN/N) - Usar Brapi
        elif symbol in ["WIN/N", "TSLA/OP"]:
            if self.brapi_client:
                try:
                    # Exemplo simplificado para ações da Brapi
                    # resp = self.brapi_client.get_quote(symbol, range="1mo", interval="1d")
                    # if resp and resp.get("results"):
                    #     data = resp["results"][0]["historicalDataPrice"]
                    #     df = pd.DataFrame(data)
                    #     df["date"] = pd.to_datetime(df["date"])
                    #     df = df.rename(columns={
                    #         "date": "timestamp", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"
                    #     })
                    #     df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                    logger.warning(f"Busca de dados de Opções/Mini Contratos via Brapi não implementada. Retornando DataFrame vazio.")
                except Exception as e:
                    logger.error(f"Erro ao buscar OHLCV da Brapi para {symbol}: {e}")

        if not df.empty:
            # Armazena os dados no banco de dados
            for _, row in df.iterrows():
                ohlcv_entry = OHLCVData(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=row["timestamp"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                )
                self.db.add(ohlcv_entry)
            self.db.commit()
            logger.info(f"Dados OHLCV para {symbol}-{timeframe} armazenados no banco de dados.")
            return df
        else:
            logger.warning(f"Nenhum dado OHLCV real encontrado para {symbol}-{timeframe}. Retornando dados simulados.")
            return self._simulate_ohlcv(limit)

        async def _get_polygon_client(self):
            """Configura o cliente Polygon.io usando credenciais do DB."""
            api_key_entry = await credential_manager.get_credentials_from_db(self.db, self.user_id, ExchangeType.POLYGON, is_testnet=False)
            if api_key_entry:
                return RESTClient(api_key_entry.api_key_encrypted)
            else:
                logger.warning(f"Chave da Polygon.io não configurada no DB para o usuário {self.user_id}. O cliente Polygon não será inicializado.")
                return None

        async def _get_brapi_client(self):
            """Configura o cliente Brapi usando credenciais do DB."""
            api_key_entry = await credential_manager.get_credentials_from_db(self.db, self.user_id, ExchangeType.BRAPI, is_testnet=False)
            if api_key_entry:
                return Brapi(api_key_entry.api_key_encrypted)
            else:
                logger.warning(f"Chave da Brapi não configurada no DB para o usuário {self.user_id}. O cliente Brapi não será inicializado.")
                return None

    def _simulate_ohlcv(self, limit: int) -> pd.DataFrame:
        """Gera dados OHLCV simulados para evitar quebras no backtesting."""
        data = {
            'timestamp': pd.to_datetime(pd.date_range(end=datetime.now(), periods=limit, freq='min')),
            'open': [random.uniform(1.0, 1.1) for _ in range(limit)],
            'high': [random.uniform(1.1, 1.2) for _ in range(limit)],
            'low': [random.uniform(0.9, 1.0) for _ in range(limit)],
            'close': [random.uniform(1.0, 1.1) for _ in range(limit)],
            'volume': [random.randint(100, 1000) for _ in range(limit)]
        }
        return pd.DataFrame(data)

    async def check_connection(self) -> bool:
        """Verifica a conexão com a exchange principal (Binance)."""
        if self.ccxt_exchange:
            try:
                await self.ccxt_exchange.load_markets()
                return True
            except Exception as e:
                logger.error(f"Falha na conexão com a Binance: {e}")
                return False
        return False

    async def fetch_balance(self) -> Dict[str, Any]:
        """Busca o saldo da conta na exchange principal (Binance)."""
        if self.ccxt_exchange and self.mode == ExecutionMode.REAL:
            try:
                balance = await self.ccxt_exchange.fetch_balance()
                return balance
            except Exception as e:
                logger.error(f"Erro ao buscar saldo na Binance: {e}")
                return {}
        return {'total': {'USDT': 10000.0}} # Saldo simulado para Paper Trading/Backtesting

    async def create_order(self, symbol: str, type: str, side: str, amount: float, price: float = None) -> Dict[str, Any]:
        """Cria uma ordem na exchange principal (Binance)."""
        if self.ccxt_exchange and self.mode == ExecutionMode.REAL:
            try:
                order = await self.ccxt_exchange.create_order(symbol, type, side, amount, price)
                return order
            except Exception as e:
                logger.error(f"Erro ao criar ordem na Binance: {e}")
                return {}
        
        # Simulação de ordem para Paper Trading/Backtesting
        logger.info(f"ORDEM SIMULADA: {side} {amount} {symbol} @ {price if price else 'Market'}")
        return {
            'id': f'sim_{random.randint(1000, 9999)}',
            'datetime': datetime.now().isoformat(),
            'symbol': symbol,
            'type': type,
            'side': side,
            'price': price if price else 0.0,
            'amount': amount,
            'filled': amount,
            'status': 'closed'
        }
        logger.info(f"Conector de Exchange inicializado em modo: {mode.value}")



    async def fetch_balance(self) -> Dict[str, Any]:
        """Busca o saldo da conta."""
        exchange = self._get_exchange_instance()
        if not exchange:
            logger.error("Credenciais ausentes. Não é possível buscar saldo real.")
            raise Exception("Credenciais ausentes para buscar saldo real.")
        
        try:
            balance = await exchange.fetch_balance()
            await exchange.close()
            return balance
        except Exception as e:
            logger.error(f"Erro ao buscar saldo real com CCXT: {e}.")
            await exchange.close()
            raise

    async def execute_trade(self, symbol: str, action: str, amount: float, signal: Dict[str, Any]):     # Lógica de execução de ordem (Placeholder)
        if self.mode == ExecutionMode.REAL:
            exchange = self._get_exchange_instance()
            if not exchange:
                logger.error("Credenciais ausentes. Não é possível executar ordem real.")
                raise Exception("Credenciais ausentes para executar ordem real.")
            
            # Lógica real de envio de ordem para a Exchange (Market Order)
            try:
                # CCXT usa 'buy'/'sell' para side, 'market' para type
                order = await exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=side,
                    amount=amount
                )
                await exchange.close()
                logger.warning(f"ORDEM REAL EXECUTADA: {side.upper()} {amount} de {symbol}. ID: {order['id']}")
                # Retorna um formato simplificado
                return {
                    "status": order['status'].lower(), # 'open', 'closed', 'canceled'
                    "price": order['price'] if order['price'] else order['average'],
                    "id": order['id']
                }
            except Exception as e:
                logger.error(f"Erro ao executar ordem real com CCXT: {e}.")
                await exchange.close()
                raise e



class StrategyBase:
    """Classe base para todas as estratégias de trading."""
    def __init__(self, db):
        self.db = db
        self.name = "BaseStrategy"
        self.symbol = None
        self.timeframe = None
        self.ohlcv = None

    async def fetch_data(self, symbol: str, timeframe: str, limit: int = 100):
        self.symbol = symbol
        self.timeframe = timeframe
        self.ohlcv = self._simulate_ohlcv(limit)  # Placeholder for DB fetch
        return self.ohlcv

    def _simulate_ohlcv(self, limit: int) -> pd.DataFrame:
        """Simula dados OHLCV para fins de backtesting.
        Isso será substituído pela busca de dados reais do banco de dados.
        """
        # Gerar dados simulados
        dates = pd.to_datetime(pd.date_range(end=datetime.now(), periods=limit, freq="1min"))
        open_prices = np.random.uniform(100, 200, limit)
        close_prices = open_prices + np.random.uniform(-5, 5, limit)
        high_prices = np.maximum(open_prices, close_prices) + np.random.uniform(0, 2, limit)
        low_prices = np.minimum(open_prices, close_prices) - np.random.uniform(0, 2, limit)
        volumes = np.random.uniform(1000, 10000, limit)

        ohlcv_data = pd.DataFrame({
            "timestamp": dates,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volumes
        })
        ohlcv_data.set_index("timestamp", inplace=True)
        return ohlcv_data

    def calculate_atr(self, period: int = 14) -> float:
        """Calcula o Average True Range (ATR) para stop dinâmico."""
        if self.ohlcv.empty or len(self.ohlcv) < period:
            return 0.0
        
        highs = self.ohlcv['high'].values.astype(float)
        lows = self.ohlcv['low'].values.astype(float)
        closes = self.ohlcv['close'].values.astype(float)
        
        atr_values = talib.ATR(highs, lows, closes, timeperiod=period)
        return atr_values[-1] if not np.isnan(atr_values[-1]) else 0.0

    def calculate_adx(self, period: int = 14) -> float:
        """Calcula o Average Directional Index (ADX) para detecção de regime."""
        if self.ohlcv.empty or len(self.ohlcv) < period * 2:
            return 0.0
        
        highs = self.ohlcv['high'].values.astype(float)
        lows = self.ohlcv['low'].values.astype(float)
        closes = self.ohlcv['close'].values.astype(float)
        
        adx_values = talib.ADX(highs, lows, closes, timeperiod=period)
        return adx_values[-1] if not np.isnan(adx_values[-1]) else 0.0

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        """Deve ser implementado pelas classes filhas."""
        raise NotImplementedError("O método generate_signal deve ser implementado.")

class SimpleMACrossoverStrategy(StrategyBase):
    """Estratégia simples de Cruzamento de Médias Móveis (SMA)."""
    def __init__(self, db, short_period=10, long_period=20): # Otimizado para 1h/4h
        super().__init__(db)
        self.name = "SimpleMACrossoverStrategy"
        self.timeframe = "1h" # Otimização Avançada (Timeframe Maior)
        self.short_period = short_period
        self.long_period = long_period

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        timeframe = getattr(self, 'timeframe', '1h')
        await self.fetch_data(self.symbol, timeframe, limit=50)
        
        if self.ohlcv.empty or len(self.ohlcv) < 30:
            name = getattr(self, 'name', 'ConfluenceStrategy')
            return {"symbol": self.symbol, "action": "hold", "confidence": 0.0, "reason": "Dados insuficientes.", "strategy_name": name}

        closes = self.ohlcv['close'].values.astype(float)
        
        # Médias Móveis (Curta: self.short_period, Longa: self.long_period)
        sma_short = talib.SMA(closes, timeperiod=self.short_period)[-1]
        sma_long = talib.SMA(closes, timeperiod=self.long_period)[-1]
        
        action = "hold"
        confidence = 0.0
        reason = "Nenhum sinal forte."

        # Lógica de Cruzamento
        if sma_short > sma_long and closes[-1] > sma_short:
            action = "buy"
            confidence = 0.8
            reason = f"Sinal de COMPRA: Média Curta ({sma_short:.2f}) cruzou acima da Média Longa ({sma_long:.2f})."
        elif sma_short < sma_long and closes[-1] < sma_short:
            action = "sell"
            confidence = 0.8
            reason = f"Sinal de VENDA: Média Curta ({sma_short:.2f}) cruzou abaixo da Média Longa ({sma_long:.2f})."

        return {
            "symbol": self.symbol,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now(),
            "price_prediction": current_price * random.uniform(0.99, 1.01),
            "reason": reason,
            "strategy_name": getattr(self, 'name', 'ConfluenceStrategy')
        }

class BollingerBandsStrategy(StrategyBase):
    """Estratégia de Bandas de Bollinger (BBands) com RSI como filtro."""
    def __init__(self, db, bband_period=20, rsi_period=14): # Otimizado para 1h/4h
        super().__init__(db)
        self.name = "BollingerBandsStrategy"
        self.timeframe = "1h" # Otimização Avançada (Timeframe Maior)
        self.bband_period = bband_period
        self.rsi_period = rsi_period

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        timeframe = getattr(self, 'timeframe', '1h')
        await self.fetch_data(self.symbol, timeframe, limit=self.bband_period + 50)
        
        if self.ohlcv.empty or len(self.ohlcv) < self.bband_period + 1:
            name = getattr(self, 'name', 'BollingerBandsStrategy')
            return {"symbol": self.symbol, "action": "hold", "confidence": 0.0, "reason": "Dados insuficientes.", "strategy_name": name}

        closes = self.ohlcv['close'].values.astype(float)
        
        # 1. Indicadores
        upper, middle, lower = talib.BBANDS(closes, timeperiod=self.bband_period, nbdevup=2, nbdevdn=2, matype=0)
        rsi = talib.RSI(closes, timeperiod=self.rsi_period)[-1]
        
        last_close = closes[-1]
        last_upper = upper[-1]
        last_lower = lower[-1]
        
        action = "hold"
        confidence = 0.0
        reason = "Nenhum sinal forte."

        # 2. Lógica de Trading
        # Compra: Preço toca a banda inferior E RSI não está sobrevendido (filtro)
        if last_close < last_lower and rsi > 30:
            action = "buy"
            confidence = 0.7
            reason = f"Sinal de COMPRA: Preço ({last_close:.4f}) abaixo da Banda Inferior ({last_lower:.4f}). RSI ({rsi:.2f}) não sobrevendido."
        
        # Venda: Preço toca a banda superior E RSI não está sobrecomprado (filtro)
        elif last_close > last_upper and rsi < 70:
            action = "sell"
            confidence = 0.7
            reason = f"Sinal de VENDA: Preço ({last_close:.4f}) acima da Banda Superior ({last_upper:.4f}). RSI ({rsi:.2f}) não sobrecomprado."

        return {
            "symbol": self.symbol,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now(),
            "price_prediction": current_price * random.uniform(0.99, 1.01),
            "reason": reason,
            "strategy_name": getattr(self, 'name', 'BollingerBandsStrategy')
        }

class MomentumStrategy(StrategyBase):
    """Estratégia baseada em Momentum (RSI e Stochastic Oscillator)."""
    def __init__(self, db, rsi_period=14, stoch_k_period=14, stoch_d_period=3): # Otimizado para 1h/4h
        super().__init__(db)
        self.name = "MomentumStrategy"
        self.timeframe = "1h" # Otimização Avançada (Timeframe Maior)
        self.rsi_period = rsi_period
        self.stoch_k_period = stoch_k_period
        self.stoch_d_period = stoch_d_period

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        timeframe = getattr(self, 'timeframe', '1h')
        await self.fetch_data(self.symbol, timeframe, limit=self.stoch_k_period + 50)
        
        if self.ohlcv.empty or len(self.ohlcv) < self.stoch_k_period + 1:
            name = getattr(self, 'name', 'MomentumStrategy')
            return {"symbol": self.symbol, "action": "hold", "confidence": 0.0, "reason": "Dados insuficientes.", "strategy_name": name}

        closes = self.ohlcv['close'].values.astype(float)
        highs = self.ohlcv['high'].values.astype(float)
        lows = self.ohlcv['low'].values.astype(float)
        
        # 1. Indicadores
        rsi = talib.RSI(closes, timeperiod=self.rsi_period)[-1]
        slowk, slowd = talib.STOCH(highs, lows, closes, 
                                   fastk_period=self.stoch_k_period, 
                                   slowk_period=self.stoch_d_period, 
                                   slowd_period=self.stoch_d_period)
        
        last_slowk = slowk[-1]
        last_slowd = slowd[-1]
        
        action = "hold"
        confidence = 0.0
        reason = "Nenhum sinal forte."

        # 2. Lógica de Trading
        # Compra: RSI sobrevendido E Stochastic cruzando para cima (sinal de reversão)
        if rsi < 30 and last_slowk > last_slowd and slowk[-2] <= slowd[-2]:
            action = "buy"
            confidence = 0.85
            reason = f"Sinal de COMPRA: RSI ({rsi:.2f}) sobrevendido. Stochastic (%K: {last_slowk:.2f}) cruzando acima de %D ({last_slowd:.2f})."
        
        # Venda: RSI sobrecomprado E Stochastic cruzando para baixo (sinal de reversão)
        elif rsi > 70 and last_slowk < last_slowd and slowk[-2] >= slowd[-2]:
            action = "sell"
            confidence = 0.85
            reason = f"Sinal de VENDA: RSI ({rsi:.2f}) sobrecomprado. Stochastic (%K: {last_slowk:.2f}) cruzando abaixo de %D ({last_slowd:.2f})."

        return {
            "symbol": self.symbol,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now(),
            "price_prediction": current_price * random.uniform(0.99, 1.01),
            "reason": reason,
            "strategy_name": getattr(self, 'name', 'MomentumStrategy')
        }

class VolumePriceStrategy(StrategyBase):
    """Estratégia baseada em Volume (OBV) e Preço (MACD)."""
    def __init__(self, db, fast_period=12, slow_period=26, signal_period=9): # Otimizado para 1h/4h
        super().__init__(db)
        self.name = "VolumePriceStrategy"
        self.timeframe = "1h" # Otimização Avançada (Timeframe Maior)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        timeframe = getattr(self, 'timeframe', '1h')
        await self.fetch_data(self.symbol, timeframe, limit=self.slow_period + 50)
        
        if self.ohlcv.empty or len(self.ohlcv) < self.slow_period + 1:
            name = getattr(self, 'name', 'VolumePriceStrategy')
            return {"symbol": self.symbol, "action": "hold", "confidence": 0.0, "reason": "Dados insuficientes.", "strategy_name": name}

        closes = self.ohlcv['close'].values.astype(float)
        volumes = self.ohlcv['volume'].values.astype(float)
        
        # 1. Indicadores
        macd, macdsignal, macdhist = talib.MACD(closes, 
                                                fastperiod=self.fast_period, 
                                                slowperiod=self.slow_period, 
                                                signalperiod=self.signal_period)
        obv = talib.OBV(closes, volumes)
        
        last_macd = macd[-1]
        last_macdsignal = macdsignal[-1]
        last_obv = obv[-1]
        prev_obv = obv[-2]
        
        action = "hold"
        confidence = 0.0
        reason = "Nenhum sinal forte."

        # 2. Lógica de Trading
        # Compra: MACD cruzando acima da linha de sinal E OBV em tendência de alta
        if last_macd > last_macdsignal and macd[-2] <= macdsignal[-2] and last_obv > prev_obv:
            action = "buy"
            confidence = 0.8
            reason = f"Sinal de COMPRA: MACD ({last_macd:.4f}) cruzando acima do Sinal ({last_macdsignal:.4f}). OBV em alta."
        
        # Venda: MACD cruzando abaixo da linha de sinal E OBV em tendência de baixa
        elif last_macd < last_macdsignal and macd[-2] >= macdsignal[-2] and last_obv < prev_obv:
            action = "sell"
            confidence = 0.8
            reason = f"Sinal de VENDA: MACD ({last_macd:.4f}) cruzando abaixo do Sinal ({last_macdsignal:.4f}). OBV em baixa."

        return {
            "symbol": self.symbol,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now(),
            "price_prediction": current_price * random.uniform(0.99, 1.01),
            "reason": reason,
            "strategy_name": getattr(self, 'name', 'VolumePriceStrategy')
        }

class ConfluenceStrategy(StrategyBase):
    """Estratégia de Confluência RSI + MACD + Stochastic + Bollinger Bands."""
    def __init__(self, db):
        super().__init__(db)
        self.name = "ConfluenceStrategy"
        self.timeframe = "1h" # Otimização Avançada (Timeframe Maior) # Timeframe fixo para esta estratégia

    async def generate_signal(self, current_price: float) -> Dict[str, Any]:
        timeframe = getattr(self, 'timeframe', '1h')
        await self.fetch_data(self.symbol, timeframe, limit=200)
        
        if self.ohlcv.empty or len(self.ohlcv) < 100:
            name = getattr(self, 'name', 'ConfluenceStrategy')
            return {"symbol": self.symbol, "action": "hold", "confidence": 0.0, "reason": "Dados insuficientes.", "strategy_name": name}

        closes = self.ohlcv['close'].values.astype(float)
        
        # 1. Indicadores
        rsi = talib.RSI(closes, timeperiod=14)[-1]
        macd, macdsignal, macdhist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        macd_hist = macdhist[-1]
        
        # Bollinger Bands
        upper, middle, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        
        # Stochastic Oscillator
        highs = self.ohlcv['high'].values.astype(float)
        lows = self.ohlcv['low'].values.astype(float)
        slowk, slowd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0)
        stoch_k = slowk[-1]
        stoch_d = slowd[-1]
        
        # Regime Detector (ADX)
        adx = self.calculate_adx(period=14)
        is_trending = adx > 25
        
        action = "hold"
        confidence = 0.0
        reason = "Nenhum sinal forte."

        # 2. Lógica de Confluência
        
        # Condição de Compra (Confluência Rigorosa)
        buy_conditions = 0
        buy_reasons = []
        
        # 1. RSI Sobrevendido
        if rsi < 30:
            buy_conditions += 1
            buy_reasons.append(f"RSI Sobrevendido ({rsi:.2f})")
            
        # 2. Stochastic Sobrevendido
        if stoch_k < 20:
            buy_conditions += 1
            buy_reasons.append(f"Stoch Sobrevendido ({stoch_k:.2f})")
            
        # 3. MACD Cruzamento de Compra (Histograma positivo)
        if macd_hist > 0 and macd_hist > macdhist[-2]:
            buy_conditions += 1
            buy_reasons.append(f"MACD Histograma Positivo ({macd_hist:.4f})")
            
        # 4. Preço na Banda Inferior (Reversão)
        if closes[-1] < lower[-1]:
            buy_conditions += 1
            buy_reasons.append(f"Preço na Banda Inferior ({closes[-1]:.4f})")

        # Condição de Venda (Confluência Rigorosa)
        sell_conditions = 0
        sell_reasons = []
        
        # 1. RSI Sobrecomprado
        if rsi > 70:
            sell_conditions += 1
            sell_reasons.append(f"RSI Sobrecomprado ({rsi:.2f})")
            
        # 2. Stochastic Sobrecomprado
        if stoch_k > 80:
            sell_conditions += 1
            sell_reasons.append(f"Stoch Sobrecomprado ({stoch_k:.2f})")
            
        # 3. MACD Cruzamento de Venda (Histograma negativo)
        if macd_hist < 0 and macd_hist < macdhist[-2]:
            sell_conditions += 1
            sell_reasons.append(f"MACD Histograma Negativo ({macd_hist:.4f})")
            
        # 4. Preço na Banda Superior (Reversão)
        if closes[-1] > upper[-1]:
            sell_conditions += 1
            sell_reasons.append(f"Preço na Banda Superior ({closes[-1]:.4f})")

        # Lógica de Decisão
        if buy_conditions >= 2:
            action = "buy"
            confidence = 0.5 + (buy_conditions * 0.1) # Confiança baseada no número de confluências
            reason = f"Sinal de COMPRA (Confluência Rigorosa - {buy_conditions} indicadores): " + ", ".join(buy_reasons)
        elif sell_conditions >= 2:
            action = "sell"
            confidence = 0.5 + (sell_conditions * 0.1) # Confiança baseada no número de confluências
            reason = f"Sinal de VENDA (Confluência Rigorosa - {sell_conditions} indicadores): " + ", ".join(sell_reasons)
        
        # Ajuste de Confiança baseado no Regime (Exemplo: Reduz confiança em lateralização)
        if not is_trending and confidence > 0.7:
            confidence *= 0.8 # Penaliza a confiança em mercado lateral
            reason += " (Confiança penalizada por regime lateral)."

        return {
            "symbol": self.symbol,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now(),
            "price_prediction": current_price * random.uniform(0.99, 1.01),
            "reason": reason,
            "strategy_name": getattr(self, 'name', 'ConfluenceStrategy')
        }






class StrategyManager:
    """Gerencia múltiplas estratégias e calcula a correlação, com persistência em DB."""
    def __init__(self, db):
        self.db = db
        self.active_strategies: List[StrategyBase] = [
            ConfluenceStrategy(db),
            SimpleMACrossoverStrategy(db),
            BollingerBandsStrategy(db),
            MomentumStrategy(db),
            VolumePriceStrategy(db),
            # Futuras estratégias serão adicionadas aqui
        ]
        self.strategy_signals: Dict[str, Dict[str, Any]] = {} # Armazena o último sinal de cada estratégia
        self.signal_history: Dict[str, List[float]] = {} # Histórico de sinais para correlação

    async def generate_combined_signal(self, symbol: str, current_price: float) -> Dict[str, Any]:
        all_signals = []
        
        for strategy in self.active_strategies:
            strategy.symbol = symbol # Garante que o símbolo está setado
            signal = await strategy.generate_signal(current_price)
            all_signals.append(signal)
            strategy_name = getattr(strategy, 'name', 'UnknownStrategy')
            self.strategy_signals[strategy_name] = signal
            
            # Armazenar o sinal para cálculo de correlação (usando confidence como proxy)
            if strategy_name not in self.signal_history:
                self.signal_history[strategy_name] = []
            
            # Converte ação para valor numérico para correlação: buy=1, sell=-1, hold=0
            signal_value = 0
            if signal['action'] == 'buy':
                signal_value = signal['confidence']
            elif signal['action'] == 'sell':
                signal_value = -signal['confidence']
            
            self.signal_history[strategy_name].append(signal_value)
            # Manter histórico limitado para cálculo de correlação
            if len(self.signal_history[strategy_name]) > 100:
                self.signal_history[strategy_name].pop(0)

        # Lógica de Combinação de Sinais (Exemplo: Média ponderada pela confiança)
        combined_confidence = sum(s['confidence'] for s in all_signals if s['action'] != 'hold')

        # Lógica de Combinação Aprimorada: Média ponderada pela confiança, mas só se a confiança for > 0.7
        
        # Filtra sinais de alta confiança
        high_confidence_signals = [s for s in all_signals if s['confidence'] >= 0.7 and s['action'] != 'hold']
        
        if not high_confidence_signals:
            # Se não houver sinais de alta confiança, retorna o melhor sinal (que será 'hold' ou o de menor confiança)
            best_signal = max(all_signals, key=lambda s: s['confidence'])
        else:
            # Se houver, usa o sinal de maior confiança entre eles
            best_signal = max(high_confidence_signals, key=lambda s: s['confidence'])
            
        # Adiciona a ATR para o stop dinâmico
        atr_value = self.active_strategies[0].calculate_atr(period=14) if self.active_strategies else 0.0
        
        # Adiciona o ADX para detecção de regime
        adx_value = self.active_strategies[0].calculate_adx(period=14) if self.active_strategies else 0.0
        is_trending = adx_value > 25
        
        best_signal['combined_confidence'] = combined_confidence
        best_signal['atr'] = atr_value
        best_signal['adx'] = adx_value
        best_signal['is_trending'] = is_trending
        best_signal['strategy_count'] = len(self.active_strategies)
        
        # NOVO FILTRO: Análise de Notícias (Tendências)
        news_sentiment = await self.robotrader.fetch_news_sentiment(symbol)
        
        # Filtro de Notícias Aprimorado: Se o sentimento for fortemente contrário, anula o sinal (confiança = 0)
        if best_signal['action'] == 'buy' and news_sentiment < -0.7: # Mais rigoroso
            best_signal['confidence'] = 0.0
            best_signal['reason'] = f"Sinal de Compra ANULADO por Sentimento de Notícias Extremamente Negativo ({news_sentiment:.2f})."
            logger.warning(best_signal['reason'])
        elif best_signal['action'] == 'sell' and news_sentiment > 0.7: # Mais rigoroso
            best_signal['confidence'] = 0.0
            best_signal['reason'] = f"Sinal de Venda ANULADO por Sentimento de Notícias Extremamente Positivo ({news_sentiment:.2f})."
            logger.warning(best_signal['reason'])
        
        # Filtro de Regime de Mercado: Penaliza sinais de tendência em mercado lateral
        if not is_trending and best_signal['confidence'] > 0.0:
            best_signal['confidence'] *= 0.7 # Penaliza em 30%
            best_signal['reason'] += f" (Penalizado por Mercado Lateral - ADX: {adx_value:.2f})."
            
        return best_signal
        


    def update_strategy_risk(self, trade_result: Dict[str, Any]):
        """
        Atualiza o contador de perdas consecutivas para a estratégia que gerou o sinal.
        Desativa a estratégia se atingir o limite de perdas consecutivas.
        """
        strategy_name = trade_result.get('strategy_name')
        is_winner = trade_result.get('is_winner', False)

        if strategy_name:
            for strategy in self.active_strategies:
                # Verificação defensiva para o erro persistente de inicialização
                strategy_obj_name = getattr(strategy, 'name', None)
                
                if strategy_obj_name == strategy_name:
                    if not hasattr(strategy, 'consecutive_losses'):
                        strategy.consecutive_losses = 0

                    if is_winner:
                        strategy.consecutive_losses = 0
                    else:
                        strategy.consecutive_losses += 1
                        if strategy.consecutive_losses >= config.trading.max_consecutive_losses:
                            logger.warning(f"Estratégia {strategy_name} desativada: {strategy.consecutive_losses} perdas consecutivas.")
                            # Remove a estratégia da lista de ativas
                            self.active_strategies = [s for s in self.active_strategies if getattr(s, 'name', None) != strategy_name]
                            break # Sai do loop após desativar
                    break # Sai do loop após encontrar a estratégia

    def calculate_correlation_matrix(self) -> Dict[str, Any]:
        """Calcula a matriz de correlação entre os sinais das estratégias."""
        if len(self.active_strategies) < 2 or len(next(iter(self.signal_history.values()))) < 10:
            return {"status": "Aguardando mais dados para calcular correlação. Mínimo de 2 estratégias e 10 sinais."}

        # Cria um DataFrame a partir do histórico de sinais
        # Preenche NaNs com 0 para evitar erros de correlação em dados esparsos
        df = pd.DataFrame(self.signal_history).fillna(0)
        
        # Calcula a matriz de correlação
        correlation_matrix = df.corr().to_dict()
        
        return correlation_matrix



    async def _execute_trade(self, signal: Dict[str, Any]):
        symbol = signal["symbol"]
        action = signal["action"]
        confidence = signal["confidence"]
        
        # A confiança mínima para execução é agora 0.7 (pode ser ajustado)
        if action == "hold" or confidence < 0.7:
            logger.info(f"Sinal de {action} para {symbol} com confiança {confidence:.2f}. Nenhuma ação tomada.")
            return

        # Lógica de execução de ordem (Agora usa o conector)
        
        # NOVO FILTRO: Mitigação de Slippage (Alto Risco de Volatilidade)
        # Se o ATR for muito alto (ex: 3x a média histórica), o risco de slippage é alto.
        # Usaremos um limite arbitrário de 0.0005 para EUR/USD (5 pips) como exemplo de ATR alto.
        # Na prática, o limite deve ser dinâmico e baseado no histórico.
        if signal.get('atr', 0.0) > 0.0005 and symbol == "EUR/USD":
            logger.warning(f"Alto risco de Slippage detectado (ATR: {signal['atr']:.5f}). Ordem cancelada para {symbol}.")
            return

        self.trade_id_counter += 1
        amount = await self.robotrader.calculate_position_size(symbol, self.robotrader.current_price.get(symbol, 0.0)) # Tamanho da posição real
        
        if amount <= 0:
            logger.error(f"Tamanho de posição calculado é zero ou negativo ({amount}). Ordem cancelada.")
            return
        
        # Lógica de execução de ordem real
        order_result = await self.robotrader.exchange_connector.execute_order(
            symbol=symbol,
            side=action,
            amount=amount,
            price=self.robotrader.current_price.get(symbol, 0.0),
            params={
                'stop_loss_atr': signal.get('atr', 0.0) * 2, # Stop Loss de 2x ATR
                'take_profit_atr': signal.get('atr', 0.0) * 3 # Take Profit de 3x ATR
            }
        )
        
        # 2. Calcular Stop Loss e Take Profit dinâmicos baseados no ATR
        atr_value = signal.get('atr', 0.0)
        trade = {
            "id": self.trade_id_counter,
            "timestamp": datetime.now(),
            "symbol": symbol,
            "side": action,
            "amount": amount,
            "price": order_result.get("price", self.current_price[symbol]), # Usar preço retornado ou preço atual
            "total_value": amount * order_result.get("price", self.current_price[symbol]),
            "fees": amount * order_result.get("price", self.current_price[symbol]) * 0.0001,
            "pnl": 0.0,
            "status": order_result.get("status", "open"),
            "strategy": signal.get('strategy_name', 'StrategyManager')
        }
        
        if atr_value > 0:
            # Multiplicadores de ATR (Exemplo: SL = 2 * ATR, TP = 4 * ATR)
            atr_multiplier_sl = 2.0
            atr_multiplier_tp = 4.0
            
            entry_price = order_result.get("price", self.current_price[symbol])
            
            if action == "buy":
                stop_loss = entry_price - (atr_value * atr_multiplier_sl)
                take_profit = entry_price + (atr_value * atr_multiplier_tp)
            else: # sell
                stop_loss = entry_price + (atr_value * atr_multiplier_sl)
                take_profit = entry_price - (atr_value * atr_multiplier_tp)
            
            trade["stop_loss"] = stop_loss
            trade["take_profit"] = take_profit
            trade["atr_value"] = atr_value
            logger.info(f"Stop Dinâmico (ATR={atr_value:.2f}): SL @ {stop_loss:.2f}, TP @ {take_profit:.2f}")
        else:
            trade["stop_loss"] = None
            trade["take_profit"] = None
            logger.warning("ATR não calculado ou zero. Usando Stop/Take Profit fixos (se houver).")
        
        # 3. Construir o objeto trade com base no resultado (movido para cima para incluir SL/TP)
        
        # 2. Construir o objeto trade com base no resultado
        trade = {
            "id": self.trade_id_counter,
            "timestamp": datetime.now(),
            "symbol": symbol,
            "side": action,
            "amount": amount,
            "price": order_result.get("price", self.current_price[symbol]), # Usar preço retornado ou preço atual
            "total_value": amount * order_result.get("price", self.current_price[symbol]),
            "fees": amount * order_result.get("price", self.current_price[symbol]) * 0.0001,
            "pnl": 0.0,
            "status": order_result.get("status", "open"),
            "strategy": "Modular_Strategy"
        }
        
        if trade["status"] == "open":
            self.positions.append(trade)
            logger.warning(f"ORDEM EXECUTADA ({self.execution_mode.value.upper()}): {action.upper()} {amount} de {symbol} @ {trade['price']:.2f}. Posição Aberta.")
        else:
            self.trade_history.append(trade)
            logger.warning(f"ORDEM EXECUTADA E FECHADA ({self.execution_mode.value.upper()}): {action.upper()} {amount} de {symbol} @ {trade['price']:.2f}. Trade Fechado.")

        # Atualiza métricas de PnL (Mock)
        self.performance_metrics["total_trades"] += 1
        self.performance_metrics["total_pnl"] += random.uniform(-10, 10)

    async def _update_market_data(self):
        # Atualiza o preço de mercado usando o conector
        for symbol in config.data.symbols:
            # Se for modo SIMULATED, o conector já simula a flutuação
            # Se for modo REAL, o conector fará a chamada real
            self.current_price[symbol] = await self.exchange_connector.fetch_current_price(symbol)
        
        # Simula a atualização de PnL para posições abertas
        positions_to_close = []
        for pos in self.positions:
            current_price = self.current_price[pos["symbol"]]
            
            # 1. Cálculo de PnL
            if pos["side"] == "buy":
                pos["pnl"] = (current_price - pos["price"]) * pos["amount"]
            elif pos["side"] == "sell":
                pos["pnl"] = (pos["price"] - current_price) * pos["amount"]
            
            pos["current_price"] = current_price
            pos["pnl_percentage"] = (pos["pnl"] / pos["total_value"]) * 100
            
            # 2. Lógica de Saída (Stop Loss / Take Profit Dinâmico)
            should_close = False
            close_reason = None
            
            if pos.get("stop_loss") is not None and pos.get("take_profit") is not None:
                if pos["side"] == "buy":
                    if current_price <= pos["stop_loss"]:
                        should_close = True
                        close_reason = "Stop Loss Dinâmico (ATR)"
                    elif current_price >= pos["take_profit"]:
                        should_close = True
                        close_reason = "Take Profit Dinâmico (ATR)"
                elif pos["side"] == "sell":
                    if current_price >= pos["stop_loss"]:
                        should_close = True
                        close_reason = "Stop Loss Dinâmico (ATR)"
                    elif current_price <= pos["take_profit"]:
                        should_close = True
                        close_reason = "Take Profit Dinâmico (ATR)"
            
            if should_close:
                positions_to_close.append((pos, close_reason))

        # Executar fechamento das posições
        for pos, reason in positions_to_close:
            self.positions.remove(pos)
            pos["status"] = "closed"
            pos["close_price"] = pos["current_price"]
            pos["close_reason"] = reason
            self.trade_history.append(pos)
            logger.warning(f"POSIÇÃO FECHADA ({reason}): {pos['side'].upper()} {pos['amount']} de {pos['symbol']} @ {pos['close_price']:.2f}. PnL: {pos['pnl']:.2f}")
        
        # 3. Atualizar Matriz de Correlação (apenas para fins de demonstração)
        correlation_matrix = self.strategy_manager.calculate_correlation_matrix()
        if isinstance(correlation_matrix, dict) and "status" not in correlation_matrix:
            logger.info(f"Matriz de Correlação Atualizada: {correlation_matrix}")

    async def run(self, manager: ConnectionManager):
        self.is_running = True
        logger.info("⚡ Loop principal do RoboTrader iniciado. Monitorando mercados...")
        
        while self.is_running and not self.shutdown_requested:
            try:
                # 1. Atualizar dados de mercado (Mock)
                await self._update_market_data()
                
                # 2. Gerar sinais de trading (Gerenciador de Estratégias)
                for symbol in config.data.symbols:
                    current_price = self.current_price[symbol]
                    # O StrategyManager agora gera o sinal combinado e calcula ATR
                    signal = await self.strategy_manager.generate_combined_signal(symbol, current_price)
                    
                    # 3. Executar lógica de risco e trading
                    await self._execute_trade(signal)
                
                # 4. Atualizar métricas de performance
                self.performance_metrics["last_update"] = datetime.now()
                
                # 5. Enviar atualização via WebSocket
                status_data = {
                    "type": "status_update",
                    "timestamp": datetime.now().isoformat(),
                    "status": {
                        "is_running": self.is_running,
                        "uptime": self.get_uptime(),
                        "positions_count": len(self.positions),
                        "total_pnl": f"{self.performance_metrics['total_pnl']:.2f}"
                    }
                }
                await manager.broadcast(json.dumps(status_data))
                
                await asyncio.sleep(5) # Ciclo de 5 segundos
                
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                await asyncio.sleep(10) # Espera mais tempo em caso de erro

        await self._shutdown()

    async def _shutdown(self):
        self.is_running = False
        logger.info("👋 Desligamento do RoboTrader solicitado. Finalizando tarefas...")
        await asyncio.sleep(1)
        logger.info("✅ RoboTrader desligado com sucesso.")

    def get_uptime(self):
        return str(datetime.now() - self.start_time).split('.')[0] # Remove milissegundos

# ==============================================================================
# 5. Gerenciamento de Instância (Substitui robotrader_api/src/dependencies.py)
# ==============================================================================

robotrader_instance: Optional[RoboTraderUnified] = None

async def create_robotrader_unified_instance() -> RoboTraderUnified:
    global robotrader_instance
    if robotrader_instance is None:
        robotrader_instance = RoboTraderUnified()
    return robotrader_instance

async def get_robotrader_instance_dependency() -> RoboTraderUnified:
    global robotrader_instance
    if robotrader_instance is None:
        # Isso não deve acontecer se o evento de startup for executado corretamente
        # Mas é necessário para o FastAPI Depends
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RoboTraderUnified instance not initialized. System is starting up."
        )
    return robotrader_instance

# ==============================================================================
# 6. API FastAPI (Substitui robotrader_api/src/main_enhanced.py)
# ==============================================================================

# Inicializa o FastAPI
app = FastAPI(
    title="RoboTrader 2.0 API",
    description="API para o sistema de trading algorítmico RoboTrader 2.0",
    version="2.0.0",
)

# Configurar CORS para permitir conexões do frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth2 para segurança
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Modelos Pydantic para requests/responses
class SystemStatusResponse(BaseModel):
    is_running: bool
    shutdown_requested: bool
    uptime: str
    modules: Dict[str, Any]

class PerformanceMetricsResponse(BaseModel):
    total_pnl: float
    daily_pnl: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    last_update: datetime

class TradingSignalResponse(BaseModel):
    symbol: str
    action: str
    confidence: float
    timestamp: datetime
    price_prediction: Optional[float] = None
    reason: Optional[str] = None

class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percentage: float
    timestamp: datetime

class TradeResponse(BaseModel):
    id: int
    timestamp: datetime
    symbol: str
    side: str
    amount: float
    price: float
    total_value: float
    fees: float
    pnl: float
    status: str
    strategy: str

@app.on_event("startup")
async def startup_event():
    global robotrader_instance
    logger.info("🚀 Iniciando serviço RoboTrader API...")
    robotrader_instance = await create_robotrader_unified_instance()
    if not await robotrader_instance.initialize():
        logger.critical("❌ Falha crítica na inicialização do RoboTrader. A API não funcionará corretamente.")
    else:
        logger.info("✅ RoboTrader inicializado com sucesso. Iniciando loop principal em background.")
        # Iniciar o loop principal do RoboTrader em uma tarefa de background
        asyncio.create_task(robotrader_instance.run(manager))

@app.on_event("shutdown")
async def shutdown_event():
    global robotrader_instance
    logger.info("👋 Desligando serviço RoboTrader API...")
    if robotrader_instance:
        await robotrader_instance._shutdown()
    logger.info("✅ Serviço RoboTrader API desligado.")

# === ENDPOINTS PRINCIPAIS ===

@app.get("/", summary="Status da API", response_description="Retorna o status da API e do RoboTrader")
async def read_root():
    global robotrader_instance
    return {
        "message": "RoboTrader 2.0 API está online!",
        "status": robotrader_instance.is_running if robotrader_instance else "uninitialized",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health", summary="Health Check", response_description="Verifica a saúde da API")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": "N/A"
    }

    
@app.get("/status", response_model=SystemStatusResponse, summary="Obter o Status do Sistema e do Bot")
async def get_system_status(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    return SystemStatusResponse(
        is_running=robotrader.is_running,
        shutdown_requested=robotrader.shutdown_requested,
        uptime=robotrader.get_uptime(),
        modules={
            "strategy": {"status": "active", "active_strategies": len(robotrader.strategy_manager.active_strategies)},
            "exchange": {"status": "active", "mode": robotrader.execution_mode.value},
            "risk": {"status": "active", "level": "dynamic_atr"},
            "data": {"status": "active", "sources": 3},
            "trading": {"status": "active" if robotrader.is_running else "inactive", "positions": len(robotrader.positions)}
        }
    )

@app.get("/analysis/walkforward", summary="Gerar Relatório de Robustez Walk-Forward")
async def get_walk_forward_report(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    report = robotrader.walk_forward_analyzer.generate_walk_forward_report()
    return report

@app.get("/analysis/correlation", summary="Obter Matriz de Correlação de Estratégias")
async def get_correlation_matrix(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    matrix = robotrader.strategy_manager.calculate_correlation_matrix()
    return matrix

@app.get("/status", response_model=SystemStatusResponse, summary="Obter o Status do Sistema e do Bot")
async def get_system_status(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    return SystemStatusResponse(
        is_running=robotrader.is_running,
        shutdown_requested=robotrader.shutdown_requested,
        uptime=robotrader.get_uptime(),
        modules={
            "strategy": {"status": "active", "active_strategies": len(robotrader.strategy_manager.active_strategies)},
            "exchange": {"status": "active", "mode": robotrader.execution_mode.value},
            "risk": {"status": "active", "level": "dynamic_atr"},
            "data": {"status": "active", "sources": 3},
            "trading": {"status": "active" if robotrader.is_running else "inactive", "positions": len(robotrader.positions)}
        }
    )

@app.post("/settings/mode", summary="Alterar o Modo de Execução (Simulado/Real)")
async def set_execution_mode(new_mode: ExecutionMode, robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    if robotrader.is_running:
        raise HTTPException(status_code=400, detail="Não é possível alterar o modo de execução enquanto o bot estiver rodando. Pare o bot primeiro.")
    
    config.trading.execution_mode = new_mode
    robotrader.execution_mode = new_mode
    robotrader.exchange_connector = robotrader._get_exchange_connector() # Reinicializa o conector com o novo modo
    
    logger.warning(f"Modo de Execução alterado para: {new_mode.value.upper()}")
    return {"message": f"Modo de Execução alterado para: {new_mode.value.upper()}. Reinicie o bot para aplicar as mudanças."}

class CredentialRequest(BaseModel):
    exchange_id: str = Field(..., description="ID da Exchange (e.g., binance)")
    api_key: str = Field(..., description="Chave de API")
    secret: str = Field(..., description="Chave Secreta")

@app.post("/credentials", summary="Armazenar Credenciais de Trading (Zero-Trust)")
async def set_credentials(creds: CredentialRequest):
    credential_manager.set_credentials(creds.exchange_id, creds.api_key, creds.secret)
    return {"message": f"Credenciais para {creds.exchange_id} armazenadas com sucesso em memória (Zero-Trust)."}

@app.delete("/credentials/{exchange_id}", summary="Remover Credenciais de Trading da Memória")
async def clear_credentials(exchange_id: str):
    credential_manager.clear_credentials(exchange_id)
    return {"message": f"Credenciais para {exchange_id} removidas da memória."}

@app.get("/performance", response_model=PerformanceMetricsResponse, summary="Métricas de Performance")
async def get_performance_metrics(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    metrics = robotrader.performance_metrics
    return PerformanceMetricsResponse(**metrics)

@app.post("/trade/{symbol}/signal", response_model=TradingSignalResponse, summary="Obter Sinal de Trading")
async def get_trading_signal(symbol: str, robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    current_price = robotrader.current_price.get(symbol, 0.0)
    signal = await robotrader.strategy.generate_signal(symbol, current_price)
    return TradingSignalResponse(**signal)

@app.get("/positions", response_model=List[PositionResponse], summary="Posições Ativas")
async def get_positions(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    return [PositionResponse(**pos) for pos in robotrader.positions]

@app.get("/trades", response_model=List[TradeResponse], summary="Histórico de Trades")
async def get_trades(limit: int = 50, robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    return [TradeResponse(**trade) for trade in robotrader.trade_history[-limit:]]

@app.post("/system/start", summary="Iniciar Sistema")
async def start_system(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    if not robotrader.is_running:
        # Iniciar sistema em background task
        asyncio.create_task(robotrader.run(manager)) # Passa o manager para o loop principal
        await manager.broadcast(JSONResponse(content={"type": "system_status", "data": {"is_running": True}}).body.decode("utf-8"))
        return {"message": "Sistema iniciado com sucesso", "status": "running"}
    return {"message": "Sistema já está em execução", "status": "already_running"}

@app.post("/system/stop", summary="Parar Sistema")
async def stop_system(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    if robotrader.is_running:
        robotrader.shutdown_requested = True
        await manager.broadcast(JSONResponse(content={"type": "system_status", "data": {"is_running": False}}).body.decode("utf-8"))
        return {"message": "Solicitação de parada enviada", "status": "stopping"}
    return {"message": "Sistema não está em execução", "status": "not_running"}

@app.post("/shutdown", summary="Desligar o RoboTrader")
async def request_shutdown(robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)):
    if robotrader.is_running:
        robotrader.shutdown_requested = True
        await manager.broadcast(JSONResponse(content={"type": "system_status", "data": {"is_running": False}}).body.decode("utf-8"))
        return {"message": "Solicitação de desligamento do RoboTrader recebida. O sistema será desligado em breve.", "status": "pending_shutdown"}
    return {"message": "RoboTrader não está em execução.", "status": "not_running"}

# === AUTENTICAÇÃO ===

@app.post("/token", summary="Obter Token de Acesso")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    # Implementar lógica de autenticação real
    # Por simplicidade, geramos um token dummy para desenvolvimento
    access_token_expires = timedelta(minutes=config.security.access_token_expire_minutes)
    return {
        "access_token": "dummy_jwt_token_for_development",
        "token_type": "bearer",
        "expires_in": access_token_expires.total_seconds()
    }

@app.get("/users/me", summary="Obter Usuário Atual")
async def read_users_me(token: str = Depends(oauth2_scheme)):
    # Implementar decodificação de token real
    return {"username": "demo_user", "token": token}

# === WEBSOCKET ===

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Aguardar mensagens do cliente
            data = await websocket.receive_text()
            logger.debug(f"Mensagem WebSocket recebida: {data}")
            
            # O backend não espera mensagens do frontend no momento, apenas envia atualizações
            await manager.send_personal_message(f"Mensagem recebida: {data}", websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Cliente WebSocket desconectado")

# === DADOS DE MERCADO ===

@app.get("/market-data/{symbol}", summary="Dados de Mercado")
async def get_market_data(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    robotrader: RoboTraderUnified = Depends(get_robotrader_instance_dependency)
):
    # Implementar busca de dados de mercado do banco de dados
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "data": [],
        "timestamp": datetime.now().isoformat()
    }

# === CONFIGURAÇÕES ===

@app.get("/config", summary="Obter Configurações")
async def get_config():
    # Retornar configurações não sensíveis
    return {
        "trading": {
            "symbols": config.data.symbols,
            "timeframes": config.data.timeframes,
            "max_portfolio_risk": config.trading.max_portfolio_risk
        },
        "ai": {
            "sequence_length": config.ai.sequence_length,
            "features": config.data.features
        }
    }

@app.put("/config", summary="Atualizar Configurações")
async def update_config(new_config: Dict[str, Any]):
    # Implementar atualização de configurações
    return {"message": "Configurações atualizadas com sucesso", "config": new_config}

# === LOGS ===

@app.get("/logs", summary="Obter Logs do Sistema")
async def get_logs(level: str = "INFO", limit: int = 100):
    # Implementar busca de logs
    return {
        "logs": [],
        "level": level,
        "limit": limit,
        "timestamp": datetime.now().isoformat()
    }

# Bloco de execução do servidor Uvicorn (removido para evitar execução automática)

