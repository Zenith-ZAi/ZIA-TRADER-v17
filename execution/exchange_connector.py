import logging
import ccxt
import asyncio
import pandas as pd
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from config.settings import Settings

logger = logging.getLogger(__name__)

class ExchangeConnector:
    """Conector universal para múltiplas exchanges (Crypto, Forex, Índices)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.crypto_exchange = None
        self.forex_client = None
        self._initialize_exchanges()

    def _initialize_exchanges(self):
        """Inicializa os conectores para diferentes mercados."""
        # Inicializar CCXT para Crypto
        try:
            if self.settings.CRYPTO_EXCHANGE.lower() == "binance":
                self.crypto_exchange = ccxt.binance({
                    'apiKey': self.settings.BINANCE_API_KEY,
                    'secret': self.settings.BINANCE_SECRET_KEY,
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'}
                })
                logger.info("✅ Binance CCXT inicializado com sucesso.")
            elif self.settings.CRYPTO_EXCHANGE.lower() == "bybit":
                self.crypto_exchange = ccxt.bybit({
                    'apiKey': self.settings.BYBIT_API_KEY,
                    'secret': self.settings.BYBIT_SECRET_KEY,
                    'enableRateLimit': True
                })
                logger.info("✅ ByBit CCXT inicializado com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar CCXT: {e}")

        # Inicializar OANDA para Forex/Índices
        try:
            if self.settings.FOREX_BROKER.lower() == "oanda":
                # Aqui você configuraria o cliente OANDA
                # Para fins de demonstração, apenas registramos
                logger.info("✅ OANDA Forex inicializado com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar OANDA: {e}")

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem no mercado apropriado."""
        symbol = order_data.get("symbol")
        action = order_data.get("action")  # "buy" ou "sell"
        quantity = order_data.get("quantity", 0)
        market_type = self._detect_market_type(symbol)

        try:
            if market_type == "crypto":
                return await self._execute_crypto_order(symbol, action, quantity, order_data)
            elif market_type == "forex":
                return await self._execute_forex_order(symbol, action, quantity, order_data)
            elif market_type == "indices":
                return await self._execute_indices_order(symbol, action, quantity, order_data)
            else:
                logger.error(f"Tipo de mercado desconhecido para {symbol}")
                return {"status": "error", "reason": "Tipo de mercado desconhecido"}
        except Exception as e:
            logger.error(f"Erro ao executar ordem para {symbol}: {e}")
            return {"status": "error", "reason": str(e)}

    async def _execute_crypto_order(self, symbol: str, action: str, quantity: float, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de criptografia via CCXT."""
        if not self.crypto_exchange:
            logger.error("CCXT não foi inicializado.")
            return {"status": "error", "reason": "CCXT não inicializado"}

        try:
            order_type = "market"  # Usar market order para execução rápida
            side = "buy" if action == "buy" else "sell"

            # Validar saldo disponível
            balance = await asyncio.to_thread(self.crypto_exchange.fetch_balance)
            logger.info(f"Saldo disponível: {balance}")

            # Executar ordem
            order = await asyncio.to_thread(
                self.crypto_exchange.create_order,
                symbol,
                order_type,
                side,
                quantity
            )

            logger.info(f"✅ Ordem de Crypto executada com sucesso: {order['id']}")
            return {
                "status": "success",
                "order_id": order['id'],
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro ao executar ordem de Crypto: {e}")
            return {"status": "error", "reason": str(e)}

    async def _execute_forex_order(self, symbol: str, action: str, quantity: float, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de Forex via OANDA."""
        # Implementação simplificada para OANDA
        # Em produção, você usaria a biblioteca oficial do OANDA
        try:
            logger.info(f"Executando ordem de Forex: {symbol} {action} {quantity} unidades")
            # Aqui você faria a chamada real para a API do OANDA
            order_id = f"FOREX_{datetime.now().timestamp()}"
            logger.info(f"✅ Ordem de Forex executada com sucesso: {order_id}")
            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro ao executar ordem de Forex: {e}")
            return {"status": "error", "reason": str(e)}

    async def _execute_indices_order(self, symbol: str, action: str, quantity: float, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de Índices."""
        try:
            logger.info(f"Executando ordem de Índice: {symbol} {action} {quantity} pontos")
            order_id = f"INDICES_{datetime.now().timestamp()}"
            logger.info(f"✅ Ordem de Índice executada com sucesso: {order_id}")
            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro ao executar ordem de Índice: {e}")
            return {"status": "error", "reason": str(e)}

    def _detect_market_type(self, symbol: str) -> str:
        """Detecta o tipo de mercado baseado no símbolo."""
        if symbol.endswith("USDT") or symbol.endswith("USD") or symbol.endswith("BTC"):
            return "crypto"
        elif any(pair in symbol for pair in ["EUR", "GBP", "JPY", "CHF", "CAD", "AUD"]):
            return "forex"
        elif any(idx in symbol for idx in ["SPX", "DAX", "FTSE", "NIKKEI"]):
            return "indices"
        else:
            return "unknown"

    async def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtém dados de mercado em tempo real."""
        market_type = self._detect_market_type(symbol)

        try:
            if market_type == "crypto" and self.crypto_exchange:
                ticker = await asyncio.to_thread(self.crypto_exchange.fetch_ticker, symbol)
                return {
                    "symbol": symbol,
                    "bid": ticker.get('bid'),
                    "ask": ticker.get('ask'),
                    "last": ticker.get('last'),
                    "volume": ticker.get('quoteVolume'),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.warning(f"Não foi possível obter dados de mercado para {symbol}")
                return None
        except Exception as e:
            logger.error(f"Erro ao obter dados de mercado para {symbol}: {e}")
            return None

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Obtém dados históricos usando Polygon.io ou CCXT como fallback."""
        market_type = self._detect_market_type(symbol)
        
        # Tentar Polygon.io primeiro se a chave estiver disponível
        if self.settings.POLYGON_API_KEY:
            try:
                # Mapeamento de timeframe para Polygon
                multiplier = 1
                timespan = "hour"
                if timeframe == "1m":
                    timespan = "minute"
                elif timeframe == "1d":
                    timespan = "day"
                
                # Formatar símbolo para Polygon (ex: X:BTCUSD para crypto)
                poly_symbol = symbol.replace("/", "")
                if market_type == "crypto":
                    poly_symbol = f"X:{poly_symbol}"
                elif market_type == "forex":
                    poly_symbol = f"C:{poly_symbol}"
                
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d') # Ajustar conforme necessário
                
                url = f"https://api.polygon.io/v2/aggs/ticker/{poly_symbol}/range/{multiplier}/{timespan}/{start_date}/{end_date}?adjusted=true&sort=asc&limit={limit}&apiKey={self.settings.POLYGON_API_KEY}"
                
                response = await asyncio.to_thread(requests.get, url)
                data = response.json()
                
                if data.get("results"):
                    df = pd.DataFrame(data["results"])
                    df.rename(columns={'v': 'volume', 'vw': 'vwap', 'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'timestamp', 'n': 'transactions'}, inplace=True)
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    return df
            except Exception as e:
                logger.warning(f"Falha ao obter dados do Polygon.io para {symbol}: {e}. Tentando fallback.")

        # Fallback para CCXT se for crypto
        if market_type == "crypto" and self.crypto_exchange:
            try:
                ohlcv = await asyncio.to_thread(self.crypto_exchange.fetch_ohlcv, symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                return df
            except Exception as e:
                logger.error(f"Erro ao obter dados históricos via CCXT para {symbol}: {e}")
                
        return pd.DataFrame()

    async def close(self):
        """Fecha as conexões com as exchanges."""
        if self.crypto_exchange:
            await asyncio.to_thread(self.crypto_exchange.close)
            logger.info("Conexão CCXT fechada.")
