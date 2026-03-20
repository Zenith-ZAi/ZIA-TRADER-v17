import sqlite3
import pandas as pd
import numpy as np
import json
import pickle
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
from contextlib import contextmanager
import threading
from dataclasses import dataclass

from utils import setup_logging
from security_module import encrypt_data, decrypt_data # Importar funções de criptografia

logger = setup_logging(__name__)

@dataclass
class TradeRecord:
    """Registro de trade para o banco de dados"""
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    symbol: str = ""
    side: str = ""  # buy/sell
    amount: float = 0.0
    price: float = 0.0
    total_value: float = 0.0
    fees: float = 0.0
    pnl: float = 0.0
    strategy: str = ""
    confidence: float = 0.0
    ai_signal: str = ""
    quantum_signal: str = ""
    news_sentiment: str = ""
    risk_score: float = 0.0
    status: str = "pending"  # pending/executed/cancelled/failed

@dataclass
class ModelMetrics:
    """Métricas do modelo para o banco de dados"""
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    model_name: str = ""
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    win_rate: float = 0.0
    avg_trade_duration: float = 0.0
    model_version: str = ""

class DatabaseManager:
    """Gerenciador de banco de dados para RoboTrader"""
    
    def __init__(self, db_path: str = "robotrader.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._initialize_database()
    
    def _initialize_database(self):
        """Inicializa o banco de dados com todas as tabelas necessárias"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabela de dados de mercado
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    timeframe TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp, timeframe)
                )
            """)
            
            # Tabela de trades
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price REAL NOT NULL,
                    total_value REAL NOT NULL,
                    fees REAL DEFAULT 0.0,
                    pnl REAL DEFAULT 0.0,
                    strategy TEXT,
                    confidence REAL DEFAULT 0.0,
                    ai_signal TEXT,
                    quantum_signal TEXT,
                    news_sentiment TEXT,
                    risk_score REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabela de métricas do modelo
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    model_name TEXT NOT NULL,
                    accuracy REAL DEFAULT 0.0,
                    precision REAL DEFAULT 0.0,
                    recall REAL DEFAULT 0.0,
                    f1_score REAL DEFAULT 0.0,
                    sharpe_ratio REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    total_return REAL DEFAULT 0.0,
                    win_rate REAL DEFAULT 0.0,
                    avg_trade_duration REAL DEFAULT 0.0,
                    model_version TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabela de configurações (para dados sensíveis como API keys)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabela de modelos salvos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    model_type TEXT NOT NULL,
                    model_data BLOB NOT NULL,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabela de portfolio/posições
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0.0,
                    avg_price REAL NOT NULL DEFAULT 0.0,
                    total_value REAL NOT NULL DEFAULT 0.0,
                    unrealized_pnl REAL DEFAULT 0.0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Índices para performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_market_data_symbol_timestamp ON market_data(symbol, timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_metrics_timestamp ON model_metrics(timestamp)')
            
            conn.commit()
            logger.info("Banco de dados inicializado com sucesso")
    
    @contextmanager
    def get_connection(self):
        """Context manager para conexões com o banco"""
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row  # Para acessar colunas por nome
            try:
                yield conn
            finally:
                conn.close()
    
    def save_market_data(self, symbol: str, timeframe: str, data: pd.DataFrame) -> bool:
        """Salva dados de mercado no banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                for _, row in data.iterrows():
                    cursor.execute("""
                        INSERT OR REPLACE INTO market_data 
                        (symbol, timestamp, timeframe, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        row['timestamp'] if isinstance(row['timestamp'], str) else row['timestamp'].isoformat(),
                        timeframe,
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        float(row['volume'])
                    ))
                
                conn.commit()
                logger.debug(f"Salvos {len(data)} registros de mercado para {symbol}")
                return True
                
        except Exception as e:
            logger.error(f"Erro ao salvar dados de mercado: {e}")
            return False
    
    def get_market_data(self, symbol: str, timeframe: str, 
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       limit: Optional[int] = None) -> pd.DataFrame:
        """Recupera dados de mercado do banco"""
        try:
            with self.get_connection() as conn:
                query = """
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_data
                    WHERE symbol = ? AND timeframe = ?
                """
                params = [symbol, timeframe]
                
                if start_date:
                    query += ' AND timestamp >= ?'
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += ' AND timestamp <= ?'
                    params.append(end_date.isoformat())
                
                query += ' ORDER BY timestamp ASC'
                
                if limit:
                    query += ' LIMIT ?'
                    params.append(limit)
                
                df = pd.read_sql_query(query, conn, params=params)
                
                if not df.empty:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                return df
                
        except Exception as e:
            logger.error(f"Erro ao recuperar dados de mercado: {e}")
            return pd.DataFrame()
    
    def save_trade(self, trade: TradeRecord) -> Optional[int]:
        """Salva um trade no banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO trades 
                    (timestamp, symbol, side, amount, price, total_value, fees, pnl,
                     strategy, confidence, ai_signal, quantum_signal, news_sentiment,
                     risk_score, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.timestamp.isoformat() if trade.timestamp else datetime.now().isoformat(),
                    trade.symbol,
                    trade.side,
                    trade.amount,
                    trade.price,
                    trade.total_value,
                    trade.fees,
                    trade.pnl,
                    trade.strategy,
                    trade.confidence,
                    trade.ai_signal,
                    trade.quantum_signal,
                    trade.news_sentiment,
                    trade.risk_score,
                    trade.status
                ))
                
                trade_id = cursor.lastrowid
                conn.commit()
                logger.debug(f"Trade salvo com ID: {trade_id}")
                return trade_id
                
        except Exception as e:
            logger.error(f"Erro ao salvar trade: {e}")
            return None
    
    def get_trades(self, symbol: Optional[str] = None,
                  start_date: Optional[datetime] = None,
                  end_date: Optional[datetime] = None,
                  status: Optional[str] = None,
                  limit: Optional[int] = None) -> List[TradeRecord]:
        """Recupera trades do banco"""
        try:
            with self.get_connection() as conn:
                query = 'SELECT * FROM trades WHERE 1=1'
                params = []
                
                if symbol:
                    query += ' AND symbol = ?'
                    params.append(symbol)
                
                if start_date:
                    query += ' AND timestamp >= ?'
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += ' AND timestamp <= ?'
                    params.append(end_date.isoformat())
                
                if status:
                    query += ' AND status = ?'
                    params.append(status)
                
                query += ' ORDER BY timestamp DESC'
                
                if limit:
                    query += ' LIMIT ?'
                    params.append(limit)
                
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                trades = []
                for row in cursor.fetchall():
                    trade = TradeRecord(
                        id=row['id'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        symbol=row['symbol'],
                        side=row['side'],
                        amount=row['amount'],
                        price=row['price'],
                        total_value=row['total_value'],
                        fees=row['fees'],
                        pnl=row['pnl'],
                        strategy=row['strategy'],
                        confidence=row['confidence'],
                        ai_signal=row['ai_signal'],
                        quantum_signal=row['quantum_signal'],
                        news_sentiment=row['news_sentiment'],
                        risk_score=row['risk_score'],
                        status=row['status']
                    )
                    trades.append(trade)
                
                return trades
                
        except Exception as e:
            logger.error(f"Erro ao recuperar trades: {e}")
            return []
    
    def save_model_metrics(self, metrics: ModelMetrics) -> bool:
        """Salva métricas do modelo"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO model_metrics 
                    (timestamp, model_name, accuracy, precision, recall, f1_score,
                     sharpe_ratio, max_drawdown, total_return, win_rate,
                     avg_trade_duration, model_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metrics.timestamp.isoformat() if metrics.timestamp else datetime.now().isoformat(),
                    metrics.model_name,
                    metrics.accuracy,
                    metrics.precision,
                    metrics.recall,
                    metrics.f1_score,
                    metrics.sharpe_ratio,
                    metrics.max_drawdown,
                    metrics.total_return,
                    metrics.win_rate,
                    metrics.avg_trade_duration,
                    metrics.model_version
                ))
                
                conn.commit()
                logger.debug(f"Métricas do modelo {metrics.model_name} salvas")
                return True
                
        except Exception as e:
            logger.error(f"Erro ao salvar métricas do modelo: {e}")
            return False
    
    def save_model(self, name: str, model_type: str, model_data: Any, metadata: Dict = None) -> bool:
        """Salva um modelo treinado no banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Serializar o modelo e criptografar
                serialized_model = encrypt_data(pickle.dumps(model_data).decode('latin-1')) # Encode/decode para string
                metadata_json = json.dumps(metadata) if metadata else "{}"
                
                cursor.execute("""
                    INSERT OR REPLACE INTO saved_models 
                    (name, model_type, model_data, metadata, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    name,
                    model_type,
                    serialized_model,
                    metadata_json,
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                logger.info(f"Modelo {name} salvo no banco (criptografado)")
                return True
                
        except Exception as e:
            logger.error(f"Erro ao salvar modelo: {e}")
            return False
    
    def load_model(self, name: str) -> Optional[Tuple[Any, Dict]]:
        """Carrega um modelo treinado do banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT model_data, metadata FROM saved_models WHERE name = ?", (name,))
                row = cursor.fetchone()
                
                if row:
                    # Descriptografar e desserializar o modelo
                    decrypted_model_data = decrypt_data(row['model_data']).encode('latin-1') # Encode/decode para bytes
                    model_data = pickle.loads(decrypted_model_data)
                    metadata = json.loads(row['metadata'])
                    logger.info(f"Modelo {name} carregado do banco (descriptografado)")
                    return model_data, metadata
                return None
                
        except Exception as e:
            logger.error(f"Erro ao carregar modelo: {e}")
            return None

    def save_setting(self, key: str, value: str) -> bool:
        """Salva uma configuração (pode ser criptografada) no banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                encrypted_value = encrypt_data(value) # Criptografa o valor
                cursor.execute("""
                    INSERT OR REPLACE INTO settings (key, value)
                    VALUES (?, ?)
                """, (key, encrypted_value))
                conn.commit()
                logger.debug(f"Configuração '{key}' salva (criptografada)")
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração '{key}': {e}")
            return False

    def load_setting(self, key: str) -> Optional[str]:
        """Carrega uma configuração (descriptografada) do banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    return decrypt_data(row['value']) # Descriptografa o valor
                return None
        except Exception as e:
            logger.error(f"Erro ao carregar configuração '{key}': {e}")
            return None

    def update_portfolio(self, symbol: str, quantity: float, avg_price: float, total_value: float, unrealized_pnl: float) -> bool:
        """Atualiza a posição de um ativo no portfólio"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO portfolio 
                    (symbol, quantity, avg_price, total_value, unrealized_pnl)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    symbol, quantity, avg_price, total_value, unrealized_pnl
                ))
                conn.commit()
                logger.debug(f"Portfólio atualizado para {symbol}")
                return True
        except Exception as e:
            logger.error(f"Erro ao atualizar portfólio para {symbol}: {e}")
            return False

    def get_portfolio(self) -> List[Dict]:
        """Recupera todas as posições do portfólio"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM portfolio")
                portfolio = []
                for row in cursor.fetchall():
                    portfolio.append(dict(row))
                return portfolio
        except Exception as e:
            logger.error(f"Erro ao recuperar portfólio: {e}")
            return []

    def get_performance_metrics(self) -> Dict:
        """Recupera as últimas métricas de performance salvas"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM model_metrics ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return {}
        except Exception as e:
            logger.error(f"Erro ao recuperar métricas de performance: {e}")
            return {}

    def save_performance_metrics(self, metrics: Dict) -> bool:
        """Salva as métricas de performance (genéricas) no banco"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Assumindo que metrics é um dicionário com chaves que correspondem às colunas de model_metrics
                # e que o timestamp é tratado externamente ou gerado aqui
                timestamp = metrics.get('timestamp', datetime.now().isoformat())
                model_name = metrics.get('model_name', 'overall_performance')
                accuracy = metrics.get('accuracy', 0.0)
                precision = metrics.get('precision', 0.0)
                recall = metrics.get('recall', 0.0)
                f1_score = metrics.get('f1_score', 0.0)
                sharpe_ratio = metrics.get('sharpe_ratio', 0.0)
                max_drawdown = metrics.get('max_drawdown', 0.0)
                total_return = metrics.get('total_return', 0.0)
                win_rate = metrics.get('win_rate', 0.0)
                avg_trade_duration = metrics.get('avg_trade_duration', 0.0)
                model_version = metrics.get('model_version', 'N/A')

                cursor.execute("""
                    INSERT INTO model_metrics 
                    (timestamp, model_name, accuracy, precision, recall, f1_score,
                     sharpe_ratio, max_drawdown, total_return, win_rate,
                     avg_trade_duration, model_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    model_name,
                    accuracy,
                    precision,
                    recall,
                    f1_score,
                    sharpe_ratio,
                    max_drawdown,
                    total_return,
                    win_rate,
                    avg_trade_duration,
                    model_version
                ))
                conn.commit()
                logger.debug(f"Métricas de performance salvas: {model_name}")
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar métricas de performance: {e}")
            return False

# Instância global do gerenciador de banco de dados
db_manager = DatabaseManager()


