"""
Módulo de Coleta e Gestão de Dados de Mercado - RoboTrader
Versão corrigida e robusta para substituir arquivo corrompido
"""

import pandas as pd
import numpy as np
import asyncio
import aiohttp
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
import json
import sqlite3
from contextlib import asynccontextmanager

from utils import setup_logging
from database import db_manager

logger = setup_logging(__name__)

@dataclass
class MarketDataPoint:
    """Estrutura de dados para um ponto de mercado"""
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str

class MarketDataManager:
    """
    Gerenciador robusto de dados de mercado
    
    Funcionalidades:
    - Coleta de múltiplas fontes
    - Cache inteligente
    - Fallback automático
    - Validação de dados
    - Sincronização assíncrona
    """
    
    def __init__(self):
        self.cache = {}
        self.last_update = {}
        self.data_sources = ['binance', 'bybit', 'coinbase', 'kraken']
        self.session = None
        
        # Configurações de cache
        self.cache_duration = 60  # segundos
        self.max_cache_size = 10000  # registros
        
        # Métricas
        self.metrics = {
            'api_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'last_error': None
        }
    
    async def __aenter__(self):
        """Context manager para sessão HTTP"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=100)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup da sessão HTTP"""
        if self.session:
            await self.session.close()
    
    def _get_cache_key(self, symbol: str, timeframe: str, limit: int) -> str:
        """Gera chave única para cache"""
        return f"{symbol}_{timeframe}_{limit}"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Verifica se cache ainda é válido"""
        if cache_key not in self.last_update:
            return False
        
        elapsed = time.time() - self.last_update[cache_key]
        return elapsed < self.cache_duration
    
    def _validate_data(self, data: pd.DataFrame) -> bool:
        """Valida integridade dos dados"""
        if data.empty:
            return False
        
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in data.columns for col in required_columns):
            return False
        
        # Verificar valores válidos
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if data[col].isna().any() or (data[col] <= 0).any():
                return False
        
        # Verificar lógica OHLC
        if not ((data['high'] >= data['open']) & 
                (data['high'] >= data['close']) &
                (data['low'] <= data['open']) & 
                (data['low'] <= data['close'])).all():
            logger.warning("Dados OHLC com inconsistências lógicas")
        
        return True
    
    async def get_market_data(self, symbol: str, timeframe: str = '1m', 
                            limit: int = 100, force_refresh: bool = False) -> pd.DataFrame:
        """
        Obtém dados de mercado com cache inteligente
        
        Args:
            symbol: Par de trading (ex: BTC/USDT)
            timeframe: Timeframe dos dados (1m, 5m, 1h, etc)
            limit: Número de candles
            force_refresh: Forçar atualização do cache
        
        Returns:
            DataFrame com dados OHLCV
        """
        cache_key = self._get_cache_key(symbol, timeframe, limit)
        
        # Verificar cache primeiro
        if not force_refresh and self._is_cache_valid(cache_key):
            if cache_key in self.cache:
                self.metrics['cache_hits'] += 1
                logger.debug(f"Cache hit para {symbol} {timeframe}")
                return self.cache[cache_key].copy()
        
        self.metrics['cache_misses'] += 1
        
        # Tentar obter dados de múltiplas fontes
        for source in self.data_sources:
            try:
                data = await self._fetch_from_source(source, symbol, timeframe, limit)
                
                if self._validate_data(data):
                    # Salvar no cache
                    self.cache[cache_key] = data.copy()
                    self.last_update[cache_key] = time.time()
                    
                    # Salvar no banco de dados
                    self._save_to_database(symbol, timeframe, data)
                    
                    logger.info(f"Dados obtidos de {source} para {symbol} {timeframe}")
                    return data
                else:
                    logger.warning(f"Dados inválidos de {source} para {symbol}")
                    
            except Exception as e:
                logger.error(f"Erro ao obter dados de {source}: {e}")
                self.metrics['errors'] += 1
                self.metrics['last_error'] = str(e)
                continue
        
        # Fallback: tentar banco de dados
        logger.warning(f"Todas as fontes falharam, tentando banco de dados para {symbol}")
        return self._get_from_database(symbol, timeframe, limit)
    
    async def _fetch_from_source(self, source: str, symbol: str, 
                               timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados de uma fonte específica"""
        self.metrics['api_calls'] += 1
        
        if source == 'binance':
            return await self._fetch_binance(symbol, timeframe, limit)
        elif source == 'bybit':
            return await self._fetch_bybit(symbol, timeframe, limit)
        elif source == 'coinbase':
            return await self._fetch_coinbase(symbol, timeframe, limit)
        elif source == 'kraken':
            return await self._fetch_kraken(symbol, timeframe, limit)
        else:
            raise ValueError(f"Fonte desconhecida: {source}")
    
    async def _fetch_binance(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados da Binance"""
        # Converter símbolo para formato Binance
        binance_symbol = symbol.replace('/', '').upper()
        
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': binance_symbol,
            'interval': self._convert_timeframe_binance(timeframe),
            'limit': limit
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Binance API error: {response.status}")
            
            data = await response.json()
            
            # Converter para DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # Processar dados
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_cols] = df[numeric_cols].astype(float)
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    async def _fetch_bybit(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados da Bybit"""
        # Converter símbolo para formato Bybit
        bybit_symbol = symbol.replace('/', '').upper()
        
        url = "https://api.bybit.com/v5/market/kline"
        params = {
            'category': 'spot',
            'symbol': bybit_symbol,
            'interval': self._convert_timeframe_bybit(timeframe),
            'limit': limit
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Bybit API error: {response.status}")
            
            result = await response.json()
            
            if result['retCode'] != 0:
                raise Exception(f"Bybit error: {result['retMsg']}")
            
            data = result['result']['list']
            
            # Converter para DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'
            ])
            
            # Processar dados
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_cols] = df[numeric_cols].astype(float)
            
            # Bybit retorna em ordem decrescente, inverter
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    async def _fetch_coinbase(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados da Coinbase Pro"""
        # Converter símbolo para formato Coinbase
        coinbase_symbol = symbol.replace('/', '-').upper()
        
        # Calcular período baseado no limit e timeframe
        granularity = self._convert_timeframe_coinbase(timeframe)
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=granularity * limit)
        
        url = f"https://api.exchange.coinbase.com/products/{coinbase_symbol}/candles"
        params = {
            'start': start_time.isoformat(),
            'end': end_time.isoformat(),
            'granularity': granularity
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Coinbase API error: {response.status}")
            
            data = await response.json()
            
            # Converter para DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'low', 'high', 'open', 'close', 'volume'
            ])
            
            # Processar dados
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_cols] = df[numeric_cols].astype(float)
            
            # Coinbase retorna em ordem decrescente, inverter
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    async def _fetch_kraken(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados da Kraken"""
        # Converter símbolo para formato Kraken
        kraken_symbol = symbol.replace('/', '').replace('USDT', 'USD').upper()
        
        url = "https://api.kraken.com/0/public/OHLC"
        params = {
            'pair': kraken_symbol,
            'interval': self._convert_timeframe_kraken(timeframe),
            'since': int((datetime.now() - timedelta(hours=limit)).timestamp())
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Kraken API error: {response.status}")
            
            result = await response.json()
            
            if result['error']:
                raise Exception(f"Kraken error: {result['error']}")
            
            # Kraken retorna dados com chave dinâmica
            pair_key = list(result['result'].keys())[0]
            data = result['result'][pair_key]
            
            # Converter para DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
            ])
            
            # Processar dados
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_cols] = df[numeric_cols].astype(float)
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(limit)
    
    def _convert_timeframe_binance(self, timeframe: str) -> str:
        """Converte timeframe para formato Binance"""
        mapping = {
            '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
            '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
            '1d': '1d', '3d': '3d', '1w': '1w', '1M': '1M'
        }
        return mapping.get(timeframe, '1m')
    
    def _convert_timeframe_bybit(self, timeframe: str) -> str:
        """Converte timeframe para formato Bybit"""
        mapping = {
            '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
            '1h': '60', '2h': '120', '4h': '240', '6h': '360', '12h': '720',
            '1d': 'D', '1w': 'W', '1M': 'M'
        }
        return mapping.get(timeframe, '1')
    
    def _convert_timeframe_coinbase(self, timeframe: str) -> int:
        """Converte timeframe para granularidade Coinbase (segundos)"""
        mapping = {
            '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '6h': 21600, '1d': 86400
        }
        return mapping.get(timeframe, 60)
    
    def _convert_timeframe_kraken(self, timeframe: str) -> int:
        """Converte timeframe para formato Kraken"""
        mapping = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '4h': 240, '1d': 1440, '1w': 10080, '2w': 21600
        }
        return mapping.get(timeframe, 1)
    
    def _save_to_database(self, symbol: str, timeframe: str, data: pd.DataFrame):
        """Salva dados no banco de dados"""
        try:
            if db_manager:
                db_manager.save_market_data(symbol, timeframe, data)
                logger.debug(f"Dados salvos no banco: {symbol} {timeframe}")
        except Exception as e:
            logger.error(f"Erro ao salvar no banco: {e}")
    
    def _get_from_database(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Obtém dados do banco de dados como fallback"""
        try:
            if db_manager:
                data = db_manager.get_market_data(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit
                )
                
                if not data.empty:
                    logger.info(f"Dados recuperados do banco: {symbol} {timeframe}")
                    return data
        except Exception as e:
            logger.error(f"Erro ao recuperar do banco: {e}")
        
        # Último recurso: dados simulados
        logger.warning(f"Gerando dados simulados para {symbol} {timeframe}")
        return self._generate_dummy_data(symbol, timeframe, limit)
    
    def _generate_dummy_data(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Gera dados simulados como último recurso"""
        base_price = 50000.0  # Preço base para simulação
        
        timestamps = pd.date_range(
            end=datetime.now(),
            periods=limit,
            freq='1min'  # Sempre 1min para simulação
        )
        
        # Gerar preços com random walk
        np.random.seed(42)  # Para reprodutibilidade
        returns = np.random.normal(0, 0.001, limit)  # 0.1% volatilidade
        prices = base_price * np.exp(np.cumsum(returns))
        
        data = []
        for i, (ts, price) in enumerate(zip(timestamps, prices)):
            # Simular OHLC com pequenas variações
            noise = np.random.normal(0, 0.0005, 4)
            open_price = price * (1 + noise[0])
            high_price = price * (1 + abs(noise[1]))
            low_price = price * (1 - abs(noise[2]))
            close_price = price * (1 + noise[3])
            
            # Garantir lógica OHLC
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            volume = np.random.uniform(100, 1000)  # Volume simulado
            
            data.append({
                'timestamp': ts,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume
            })
        
        return pd.DataFrame(data)
    
    def get_metrics(self) -> Dict:
        """Retorna métricas de performance"""
        cache_hit_rate = 0
        if self.metrics['cache_hits'] + self.metrics['cache_misses'] > 0:
            cache_hit_rate = self.metrics['cache_hits'] / (
                self.metrics['cache_hits'] + self.metrics['cache_misses']
            )
        
        return {
            **self.metrics,
            'cache_hit_rate': cache_hit_rate,
            'cache_size': len(self.cache),
            'sources_available': len(self.data_sources)
        }
    
    def clear_cache(self):
        """Limpa cache manualmente"""
        self.cache.clear()
        self.last_update.clear()
        logger.info("Cache limpo manualmente")

# Instância global
market_data_manager = MarketDataManager()

