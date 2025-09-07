"""
Sistema de Migração e Persistência de Dados Robusto - RoboTrader
Implementa migração de SQLite para PostgreSQL/InfluxDB para produção.
"""

import os
import asyncio
import asyncpg
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
import json
import sqlite3
from pathlib import Path
import logging
from contextlib import asynccontextmanager

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID
import uuid

from config import config
from utils import setup_logging

logger = setup_logging(__name__)

@dataclass
class DatabaseConfig:
    """Configuração de banco de dados"""
    # PostgreSQL para dados relacionais
    postgres_host: str = os.getenv('POSTGRES_HOST', 'localhost')
    postgres_port: int = int(os.getenv('POSTGRES_PORT', '5432'))
    postgres_db: str = os.getenv('POSTGRES_DB', 'robotrader')
    postgres_user: str = os.getenv('POSTGRES_USER', 'robotrader')
    postgres_password: str = os.getenv('POSTGRES_PASSWORD', 'robotrader123')
    
    # InfluxDB para séries temporais
    influx_url: str = os.getenv('INFLUX_URL', 'http://localhost:8086')
    influx_token: str = os.getenv('INFLUX_TOKEN', 'robotrader-token')
    influx_org: str = os.getenv('INFLUX_ORG', 'robotrader')
    influx_bucket: str = os.getenv('INFLUX_BUCKET', 'market_data')
    
    # SQLite (fallback)
    sqlite_path: str = 'robotrader.db'

class PostgreSQLManager:
    """
    Gerenciador de banco PostgreSQL para dados relacionais
    
    Responsável por:
    - Configurações do sistema
    - Metadados de modelos
    - Registros de trades
    - Logs de sistema
    - Métricas de performance
    """
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.engine = None
        self.session_factory = None
        self.connection_pool = None
        
        # SQLAlchemy Base
        self.Base = declarative_base()
        self._define_tables()
    
    def _define_tables(self):
        """Define tabelas do PostgreSQL"""
        
        # Tabela de configurações
        class SystemConfig(self.Base):
            __tablename__ = 'system_config'
            
            id = Column(Integer, primary_key=True)
            key = Column(String(255), unique=True, nullable=False)
            value = Column(Text, nullable=False)
            data_type = Column(String(50), nullable=False)
            created_at = Column(DateTime, default=datetime.utcnow)
            updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        
        # Tabela de modelos
        class AIModel(self.Base):
            __tablename__ = 'ai_models'
            
            id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
            name = Column(String(255), nullable=False)
            version = Column(String(100), nullable=False)
            model_type = Column(String(100), nullable=False)
            model_path = Column(String(500), nullable=False)
            metadata = Column(Text)  # JSON
            performance_metrics = Column(Text)  # JSON
            is_active = Column(Boolean, default=False)
            created_at = Column(DateTime, default=datetime.utcnow)
            updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        
        # Tabela de trades
        class Trade(self.Base):
            __tablename__ = 'trades'
            
            id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
            timestamp = Column(DateTime, nullable=False)
            symbol = Column(String(50), nullable=False)
            side = Column(String(10), nullable=False)  # buy/sell
            amount = Column(Float, nullable=False)
            price = Column(Float, nullable=False)
            pnl = Column(Float, default=0.0)
            status = Column(String(50), nullable=False)
            order_id = Column(String(255))
            exchange = Column(String(100))
            ai_confidence = Column(Float)
            risk_level = Column(String(50))
            strategy_used = Column(String(255))
            metadata = Column(Text)  # JSON
            created_at = Column(DateTime, default=datetime.utcnow)
        
        # Tabela de métricas de performance
        class PerformanceMetric(self.Base):
            __tablename__ = 'performance_metrics'
            
            id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
            timestamp = Column(DateTime, nullable=False)
            metric_type = Column(String(100), nullable=False)
            metric_name = Column(String(255), nullable=False)
            value = Column(Float, nullable=False)
            metadata = Column(Text)  # JSON
            created_at = Column(DateTime, default=datetime.utcnow)
        
        # Tabela de logs do sistema
        class SystemLog(self.Base):
            __tablename__ = 'system_logs'
            
            id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
            timestamp = Column(DateTime, nullable=False)
            level = Column(String(20), nullable=False)
            module = Column(String(255), nullable=False)
            message = Column(Text, nullable=False)
            metadata = Column(Text)  # JSON
            created_at = Column(DateTime, default=datetime.utcnow)
        
        # Armazenar classes para uso posterior
        self.SystemConfig = SystemConfig
        self.AIModel = AIModel
        self.Trade = Trade
        self.PerformanceMetric = PerformanceMetric
        self.SystemLog = SystemLog
    
    async def initialize(self):
        """Inicializa conexão com PostgreSQL"""
        try:
            # Criar connection string
            connection_string = (
                f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}"
                f"@{self.config.postgres_host}:{self.config.postgres_port}/{self.config.postgres_db}"
            )
            
            # Criar engine SQLAlchemy
            self.engine = create_engine(
                connection_string,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                echo=False
            )
            
            # Criar tabelas
            self.Base.metadata.create_all(self.engine)
            
            # Criar session factory
            self.session_factory = sessionmaker(bind=self.engine)
            
            # Criar pool de conexões asyncpg para operações assíncronas
            self.connection_pool = await asyncpg.create_pool(
                host=self.config.postgres_host,
                port=self.config.postgres_port,
                database=self.config.postgres_db,
                user=self.config.postgres_user,
                password=self.config.postgres_password,
                min_size=5,
                max_size=20
            )
            
            logger.info("✅ PostgreSQL inicializado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar PostgreSQL: {e}")
            return False
    
    @asynccontextmanager
    async def get_connection(self):
        """Context manager para conexões assíncronas"""
        async with self.connection_pool.acquire() as connection:
            yield connection
    
    def get_session(self):
        """Obtém sessão SQLAlchemy"""
        return self.session_factory()
    
    async def save_trade(self, trade_data: Dict[str, Any]):
        """Salva registro de trade"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    INSERT INTO trades (
                        timestamp, symbol, side, amount, price, pnl, status,
                        order_id, exchange, ai_confidence, risk_level, strategy_used, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """, 
                    trade_data['timestamp'],
                    trade_data['symbol'],
                    trade_data['side'],
                    trade_data['amount'],
                    trade_data['price'],
                    trade_data.get('pnl', 0.0),
                    trade_data['status'],
                    trade_data.get('order_id'),
                    trade_data.get('exchange'),
                    trade_data.get('ai_confidence'),
                    trade_data.get('risk_level'),
                    trade_data.get('strategy_used'),
                    json.dumps(trade_data.get('metadata', {}))
                )
            logger.debug(f"Trade salvo: {trade_data['symbol']} {trade_data['side']}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar trade: {e}")
    
    async def get_trades(self, symbol: Optional[str] = None, 
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """Obtém registros de trades"""
        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []
            param_count = 0
            
            if symbol:
                param_count += 1
                query += f" AND symbol = ${param_count}"
                params.append(symbol)
            
            if start_date:
                param_count += 1
                query += f" AND timestamp >= ${param_count}"
                params.append(start_date)
            
            if end_date:
                param_count += 1
                query += f" AND timestamp <= ${param_count}"
                params.append(end_date)
            
            query += f" ORDER BY timestamp DESC LIMIT ${param_count + 1}"
            params.append(limit)
            
            async with self.get_connection() as conn:
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Erro ao obter trades: {e}")
            return []
    
    async def save_model_metadata(self, model_data: Dict[str, Any]):
        """Salva metadados do modelo"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    INSERT INTO ai_models (
                        name, version, model_type, model_path, metadata, 
                        performance_metrics, is_active
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    model_data['name'],
                    model_data['version'],
                    model_data['model_type'],
                    model_data['model_path'],
                    json.dumps(model_data.get('metadata', {})),
                    json.dumps(model_data.get('performance_metrics', {})),
                    model_data.get('is_active', False)
                )
            logger.debug(f"Metadados do modelo salvos: {model_data['name']} v{model_data['version']}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar metadados do modelo: {e}")
    
    async def close(self):
        """Fecha conexões"""
        if self.connection_pool:
            await self.connection_pool.close()
        if self.engine:
            self.engine.dispose()

class InfluxDBManager:
    """
    Gerenciador de InfluxDB para séries temporais
    
    Responsável por:
    - Dados de mercado (OHLCV)
    - Métricas de performance em tempo real
    - Indicadores técnicos
    - Sinais de IA e análises
    """
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.client = None
        self.write_api = None
        self.query_api = None
    
    async def initialize(self):
        """Inicializa conexão com InfluxDB"""
        try:
            self.client = InfluxDBClient(
                url=self.config.influx_url,
                token=self.config.influx_token,
                org=self.config.influx_org
            )
            
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.query_api = self.client.query_api()
            
            # Testar conexão
            health = self.client.health()
            if health.status == "pass":
                logger.info("✅ InfluxDB inicializado com sucesso")
                return True
            else:
                logger.error(f"❌ InfluxDB não está saudável: {health.status}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar InfluxDB: {e}")
            return False
    
    async def save_market_data(self, symbol: str, timeframe: str, data: pd.DataFrame):
        """Salva dados de mercado"""
        try:
            points = []
            
            for _, row in data.iterrows():
                point = Point("market_data") \
                    .tag("symbol", symbol) \
                    .tag("timeframe", timeframe) \
                    .field("open", float(row['open'])) \
                    .field("high", float(row['high'])) \
                    .field("low", float(row['low'])) \
                    .field("close", float(row['close'])) \
                    .field("volume", float(row['volume'])) \
                    .time(row['timestamp'], WritePrecision.MS)
                
                points.append(point)
            
            self.write_api.write(bucket=self.config.influx_bucket, record=points)
            logger.debug(f"Dados de mercado salvos: {symbol} ({len(points)} pontos)")
            
        except Exception as e:
            logger.error(f"Erro ao salvar dados de mercado: {e}")
    
    async def get_market_data(self, symbol: str, timeframe: str,
                             start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """Obtém dados de mercado"""
        try:
            query = f'''
                from(bucket: "{self.config.influx_bucket}")
                |> range(start: {start_time.isoformat()}Z, stop: {end_time.isoformat()}Z)
                |> filter(fn: (r) => r._measurement == "market_data")
                |> filter(fn: (r) => r.symbol == "{symbol}")
                |> filter(fn: (r) => r.timeframe == "{timeframe}")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> sort(columns: ["_time"])
            '''
            
            result = self.query_api.query_data_frame(query)
            
            if not result.empty:
                # Renomear colunas
                result = result.rename(columns={'_time': 'timestamp'})
                result = result[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
                result['timestamp'] = pd.to_datetime(result['timestamp'])
                
            return result
            
        except Exception as e:
            logger.error(f"Erro ao obter dados de mercado: {e}")
            return pd.DataFrame()
    
    async def save_performance_metrics(self, metrics: Dict[str, Any]):
        """Salva métricas de performance"""
        try:
            point = Point("performance") \
                .tag("metric_type", "system") \
                .field("total_trades", metrics.get('total_trades', 0)) \
                .field("successful_trades", metrics.get('successful_trades', 0)) \
                .field("total_pnl", metrics.get('total_pnl', 0.0)) \
                .field("win_rate", metrics.get('win_rate', 0.0)) \
                .field("sharpe_ratio", metrics.get('sharpe_ratio', 0.0)) \
                .field("max_drawdown", metrics.get('max_drawdown', 0.0)) \
                .time(datetime.utcnow(), WritePrecision.MS)
            
            self.write_api.write(bucket=self.config.influx_bucket, record=point)
            logger.debug("Métricas de performance salvas")
            
        except Exception as e:
            logger.error(f"Erro ao salvar métricas de performance: {e}")
    
    async def save_ai_signals(self, symbol: str, signals: Dict[str, Any]):
        """Salva sinais de IA"""
        try:
            point = Point("ai_signals") \
                .tag("symbol", symbol) \
                .tag("model_version", signals.get('model_version', 'unknown')) \
                .field("action", signals.get('action', 'hold')) \
                .field("confidence", signals.get('confidence', 0.0)) \
                .field("price_prediction", signals.get('price_prediction', 0.0)) \
                .field("direction_prediction", signals.get('direction_prediction', 0.0)) \
                .time(datetime.utcnow(), WritePrecision.MS)
            
            self.write_api.write(bucket=self.config.influx_bucket, record=point)
            logger.debug(f"Sinais de IA salvos: {symbol}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar sinais de IA: {e}")
    
    def close(self):
        """Fecha conexão"""
        if self.client:
            self.client.close()

class DatabaseMigrationManager:
    """
    Gerenciador de migração de dados
    
    Migra dados do SQLite para PostgreSQL/InfluxDB
    """
    
    def __init__(self):
        self.db_config = DatabaseConfig()
        self.postgres_manager = PostgreSQLManager(self.db_config)
        self.influx_manager = InfluxDBManager(self.db_config)
        self.sqlite_path = self.db_config.sqlite_path
    
    async def initialize(self):
        """Inicializa gerenciadores de banco"""
        postgres_ok = await self.postgres_manager.initialize()
        influx_ok = await self.influx_manager.initialize()
        
        return postgres_ok and influx_ok
    
    async def migrate_all_data(self):
        """Migra todos os dados do SQLite"""
        logger.info("🚀 Iniciando migração completa de dados...")
        
        try:
            # Verificar se SQLite existe
            if not Path(self.sqlite_path).exists():
                logger.warning(f"⚠️ Arquivo SQLite não encontrado: {self.sqlite_path}")
                return False
            
            # Migrar dados sequencialmente
            await self._migrate_market_data()
            await self._migrate_trades()
            await self._migrate_models()
            await self._migrate_performance_metrics()
            
            logger.info("✅ Migração completa concluída com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na migração: {e}")
            return False
    
    async def _migrate_market_data(self):
        """Migra dados de mercado para InfluxDB"""
        logger.info("📊 Migrando dados de mercado...")
        
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Verificar se tabela existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_data'")
            if not cursor.fetchone():
                logger.warning("⚠️ Tabela market_data não encontrada no SQLite")
                return
            
            # Obter dados
            cursor.execute("""
                SELECT symbol, timeframe, timestamp, open, high, low, close, volume
                FROM market_data
                ORDER BY timestamp
            """)
            
            rows = cursor.fetchall()
            
            if not rows:
                logger.warning("⚠️ Nenhum dado de mercado encontrado")
                return
            
            # Agrupar por símbolo e timeframe
            data_groups = {}
            for row in rows:
                symbol, timeframe = row[0], row[1]
                key = f"{symbol}_{timeframe}"
                
                if key not in data_groups:
                    data_groups[key] = []
                
                data_groups[key].append({
                    'timestamp': pd.to_datetime(row[2]),
                    'open': row[3],
                    'high': row[4],
                    'low': row[5],
                    'close': row[6],
                    'volume': row[7]
                })
            
            # Migrar cada grupo
            for key, data in data_groups.items():
                symbol, timeframe = key.split('_', 1)
                df = pd.DataFrame(data)
                await self.influx_manager.save_market_data(symbol, timeframe, df)
            
            conn.close()
            logger.info(f"✅ {len(rows)} registros de dados de mercado migrados")
            
        except Exception as e:
            logger.error(f"❌ Erro na migração de dados de mercado: {e}")
    
    async def _migrate_trades(self):
        """Migra registros de trades para PostgreSQL"""
        logger.info("💰 Migrando registros de trades...")
        
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Verificar se tabela existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if not cursor.fetchone():
                logger.warning("⚠️ Tabela trades não encontrada no SQLite")
                return
            
            # Obter dados
            cursor.execute("""
                SELECT timestamp, symbol, side, amount, price, pnl, status,
                       order_id, ai_confidence, risk_level
                FROM trades
                ORDER BY timestamp
            """)
            
            rows = cursor.fetchall()
            
            for row in rows:
                trade_data = {
                    'timestamp': pd.to_datetime(row[0]),
                    'symbol': row[1],
                    'side': row[2],
                    'amount': row[3],
                    'price': row[4],
                    'pnl': row[5] or 0.0,
                    'status': row[6],
                    'order_id': row[7],
                    'ai_confidence': row[8],
                    'risk_level': row[9],
                    'exchange': 'migrated',
                    'strategy_used': 'legacy',
                    'metadata': {}
                }
                
                await self.postgres_manager.save_trade(trade_data)
            
            conn.close()
            logger.info(f"✅ {len(rows)} registros de trades migrados")
            
        except Exception as e:
            logger.error(f"❌ Erro na migração de trades: {e}")
    
    async def _migrate_models(self):
        """Migra metadados de modelos para PostgreSQL"""
        logger.info("🧠 Migrando metadados de modelos...")
        
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Verificar se tabela existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")
            if not cursor.fetchone():
                logger.warning("⚠️ Tabela models não encontrada no SQLite")
                return
            
            # Obter dados
            cursor.execute("""
                SELECT name, model_type, model_data, metadata
                FROM models
            """)
            
            rows = cursor.fetchall()
            
            for row in rows:
                model_data = {
                    'name': row[0],
                    'version': '1.0',  # Versão padrão para modelos migrados
                    'model_type': row[1],
                    'model_path': f"/models/migrated/{row[0]}.pkl",
                    'metadata': json.loads(row[3]) if row[3] else {},
                    'performance_metrics': {},
                    'is_active': False
                }
                
                await self.postgres_manager.save_model_metadata(model_data)
            
            conn.close()
            logger.info(f"✅ {len(rows)} modelos migrados")
            
        except Exception as e:
            logger.error(f"❌ Erro na migração de modelos: {e}")
    
    async def _migrate_performance_metrics(self):
        """Migra métricas de performance para InfluxDB"""
        logger.info("📈 Migrando métricas de performance...")
        
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Verificar se tabela existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='performance_metrics'")
            if not cursor.fetchone():
                logger.warning("⚠️ Tabela performance_metrics não encontrada no SQLite")
                return
            
            # Obter dados
            cursor.execute("""
                SELECT timestamp, total_trades, successful_trades, total_pnl,
                       win_rate, sharpe_ratio, max_drawdown
                FROM performance_metrics
                ORDER BY timestamp
            """)
            
            rows = cursor.fetchall()
            
            for row in rows:
                metrics = {
                    'total_trades': row[1] or 0,
                    'successful_trades': row[2] or 0,
                    'total_pnl': row[3] or 0.0,
                    'win_rate': row[4] or 0.0,
                    'sharpe_ratio': row[5] or 0.0,
                    'max_drawdown': row[6] or 0.0
                }
                
                await self.influx_manager.save_performance_metrics(metrics)
            
            conn.close()
            logger.info(f"✅ {len(rows)} métricas de performance migradas")
            
        except Exception as e:
            logger.error(f"❌ Erro na migração de métricas: {e}")
    
    async def backup_sqlite(self):
        """Faz backup do SQLite antes da migração"""
        try:
            if Path(self.sqlite_path).exists():
                backup_path = f"{self.sqlite_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                import shutil
                shutil.copy2(self.sqlite_path, backup_path)
                logger.info(f"✅ Backup do SQLite criado: {backup_path}")
                return backup_path
            else:
                logger.warning("⚠️ Arquivo SQLite não encontrado para backup")
                return None
                
        except Exception as e:
            logger.error(f"❌ Erro ao fazer backup do SQLite: {e}")
            return None
    
    async def close(self):
        """Fecha todas as conexões"""
        await self.postgres_manager.close()
        self.influx_manager.close()

class RobustDatabaseManager:
    """
    Gerenciador de banco de dados robusto unificado
    
    Combina PostgreSQL e InfluxDB para máxima performance e confiabilidade
    """
    
    def __init__(self):
        self.db_config = DatabaseConfig()
        self.postgres_manager = PostgreSQLManager(self.db_config)
        self.influx_manager = InfluxDBManager(self.db_config)
        self.is_initialized = False
    
    async def initialize(self):
        """Inicializa todos os gerenciadores"""
        try:
            postgres_ok = await self.postgres_manager.initialize()
            influx_ok = await self.influx_manager.initialize()
            
            self.is_initialized = postgres_ok and influx_ok
            
            if self.is_initialized:
                logger.info("✅ Sistema de banco de dados robusto inicializado")
            else:
                logger.error("❌ Falha na inicialização do sistema de banco de dados")
            
            return self.is_initialized
            
        except Exception as e:
            logger.error(f"❌ Erro na inicialização: {e}")
            return False
    
    # Métodos de conveniência que delegam para os gerenciadores apropriados
    
    async def save_market_data(self, symbol: str, timeframe: str, data: pd.DataFrame):
        """Salva dados de mercado (InfluxDB)"""
        return await self.influx_manager.save_market_data(symbol, timeframe, data)
    
    async def get_market_data(self, symbol: str, timeframe: str,
                             start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """Obtém dados de mercado (InfluxDB)"""
        return await self.influx_manager.get_market_data(symbol, timeframe, start_time, end_time)
    
    async def save_trade(self, trade_data: Dict[str, Any]):
        """Salva registro de trade (PostgreSQL)"""
        return await self.postgres_manager.save_trade(trade_data)
    
    async def get_trades(self, **kwargs) -> List[Dict[str, Any]]:
        """Obtém registros de trades (PostgreSQL)"""
        return await self.postgres_manager.get_trades(**kwargs)
    
    async def save_model_metadata(self, model_data: Dict[str, Any]):
        """Salva metadados do modelo (PostgreSQL)"""
        return await self.postgres_manager.save_model_metadata(model_data)
    
    async def save_performance_metrics(self, metrics: Dict[str, Any]):
        """Salva métricas de performance (InfluxDB)"""
        return await self.influx_manager.save_performance_metrics(metrics)
    
    async def save_ai_signals(self, symbol: str, signals: Dict[str, Any]):
        """Salva sinais de IA (InfluxDB)"""
        return await self.influx_manager.save_ai_signals(symbol, signals)
    
    async def close(self):
        """Fecha todas as conexões"""
        await self.postgres_manager.close()
        self.influx_manager.close()

# Instância global
robust_db_manager: Optional[RobustDatabaseManager] = None

async def initialize_robust_database() -> RobustDatabaseManager:
    """Inicializa o sistema de banco de dados robusto"""
    global robust_db_manager
    robust_db_manager = RobustDatabaseManager()
    await robust_db_manager.initialize()
    return robust_db_manager

async def migrate_from_sqlite():
    """Executa migração completa do SQLite"""
    migration_manager = DatabaseMigrationManager()
    
    try:
        # Inicializar
        if not await migration_manager.initialize():
            logger.error("❌ Falha na inicialização da migração")
            return False
        
        # Fazer backup
        backup_path = await migration_manager.backup_sqlite()
        if backup_path:
            logger.info(f"📦 Backup criado: {backup_path}")
        
        # Executar migração
        success = await migration_manager.migrate_all_data()
        
        if success:
            logger.info("🎉 Migração concluída com sucesso!")
        else:
            logger.error("❌ Migração falhou")
        
        return success
        
    finally:
        await migration_manager.close()

if __name__ == "__main__":
    # Executar migração
    asyncio.run(migrate_from_sqlite())

