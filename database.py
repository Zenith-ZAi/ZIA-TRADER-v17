from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone
import enum
import os

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Retorna UTC sem tzinfo para compatibilidade com DateTime legado do schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class MarketType(enum.Enum):
    CRYPTO = "crypto"
    FOREX = "forex"
    INDICES = "indices"
    STOCKS = "stocks"

class OrderStatus(enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

class AccountState(Base):
    __tablename__ = 'account_state'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, unique=True, nullable=False)
    balance = Column(Float, default=0.0)
    initial_capital = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)

class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)
    open_time = Column(DateTime, default=utc_now)
    close_time = Column(DateTime)

class RuntimePositionState(Base):
    __tablename__ = 'runtime_position_state'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    breakeven_trigger = Column(Float)
    order_id = Column(String)
    is_open = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class DailyPNL(Base):
    __tablename__ = 'daily_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class WeeklyPNL(Base):
    __tablename__ = 'weekly_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    week_start_date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class MonthlyPNL(Base):
    __tablename__ = 'monthly_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    month_start_date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class Drawdown(Base):
    __tablename__ = 'drawdowns'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    start_time = Column(DateTime, default=utc_now)
    end_time = Column(DateTime)
    peak_balance = Column(Float, nullable=False)
    trough_balance = Column(Float, nullable=False)
    max_drawdown_percentage = Column(Float, nullable=False)
    drawdown = Column(Float, nullable=False, default=0.0)

class OrderHistory(Base):
    __tablename__ = 'order_history'
    __table_args__ = (Index("ix_order_history_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    order_id = Column(String, unique=True, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    price = Column(Float)
    quantity = Column(Float)
    status = Column(Enum(OrderStatus), nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)

class ExecutionHistory(Base):
    __tablename__ = 'execution_history'
    __table_args__ = (Index("ix_execution_history_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    execution_id = Column(String, unique=True, nullable=False)
    order_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    filled_price = Column(Float, nullable=False)
    filled_quantity = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)

class Trade(Base):
    __tablename__ = 'trades'
    __table_args__ = (Index("ix_trades_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    confidence = Column(Float)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)

class WhaleActivity(Base):
    __tablename__ = 'whale_activity'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    sentiment = Column(String)
    timestamp = Column(DateTime, default=utc_now)

class NewsArticle(Base):
    __tablename__ = 'news_articles'
    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    symbol = Column(String, nullable=True)
    title = Column(String, nullable=False)
    summary = Column(String)
    url = Column(String)
    published_at = Column(DateTime)
    sentiment_score = Column(Float, default=0.0)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now)


class TrendSnapshot(Base):
    __tablename__ = 'trend_snapshots'
    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    trend_score = Column(Float, default=0.0)
    market_cap_rank = Column(Integer)
    price_change_24h = Column(Float)
    observed_at = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)


class AIObservation(Base):
    __tablename__ = 'ai_observations'
    __table_args__ = (Index("ix_ai_observations_symbol_observed_at", "symbol", "observed_at"),)
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    observed_at = Column(DateTime, default=utc_now, index=True)
    mode = Column(String, nullable=False, default="shadow")
    action = Column(String, nullable=False, default="hold")
    candidate_action = Column(String, nullable=False, default="hold")
    confidence = Column(Float, default=0.0)
    model_action = Column(String, nullable=False, default="hold")
    model_confidence = Column(Float, default=0.0)
    market_signal_action = Column(String, nullable=False, default="hold")
    market_signal_confidence = Column(Float, default=0.0)
    price = Column(Float, default=0.0)
    news_sentiment = Column(Float, default=0.0)
    trend_score = Column(Float, default=0.0)
    event_blocked = Column(Boolean, default=False)
    risk_valid = Column(Boolean, default=False)
    decision_latency_ms = Column(Float, default=0.0)
    news_latency_ms = Column(Float, default=0.0)
    forward_return = Column(Float, nullable=True)
    outcome_label = Column(Integer, nullable=True)
    metadata_json = Column(JSON)


class MarketPattern(Base):
    __tablename__ = 'market_patterns'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    strategy = Column(String, nullable=False, default="pullback")
    observed_at = Column(DateTime, default=utc_now, index=True)
    pattern_type = Column(String, nullable=False, default="pullback")
    signature_json = Column(JSON, nullable=False, default=dict)
    entry_price = Column(Float, default=0.0)
    atr = Column(Float, default=0.0)
    outcome_atr = Column(Float, nullable=True)
    outcome_label = Column(Integer, nullable=True)
    sample_size = Column(Integer, default=1)
    source_observation_id = Column(Integer, nullable=True)
    metadata_json = Column(JSON)


class SystemLog(Base):
    __tablename__ = 'system_logs'
    id = Column(Integer, primary_key=True)
    level = Column(String)
    account_id = Column(String, nullable=True)
    message = Column(String)
    module = Column(String)
    timestamp = Column(DateTime, default=utc_now)

def get_engine(database_url: str):
    return create_engine(database_url)

def get_session_local(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db(engine):
    if engine.dialect.name == "sqlite":
        if os.getenv("ENVIRONMENT", "development").strip().lower() in {"prod", "production"}:
            raise RuntimeError("SQLite/create_all não é permitido em produção; configure PostgreSQL e execute Alembic")
        Base.metadata.create_all(engine)
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"Dialeto de banco não suportado para migrações: {engine.dialect.name}")
    from infra.db_migrations import upgrade_database

    upgrade_database(engine)


class OrderIntent(Base):
    """Intenção local idempotente antes e durante o envio à exchange."""
    __tablename__ = "order_intents"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    client_order_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False, default="market")
    quantity = Column(Float, nullable=False)
    price = Column(Float)
    status = Column(String, nullable=False, default="reserved")
    exchange_order_id = Column(String)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String)
    payload_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class ReconciliationSnapshot(Base):
    __tablename__ = "reconciliation_snapshots"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    open_orders_count = Column(Integer, default=0)
    positions_count = Column(Integer, default=0)
    payload_json = Column(JSON)
    observed_at = Column(DateTime, default=utc_now, index=True)


class ProtectionOrder(Base):
    __tablename__ = "protection_orders"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    parent_client_order_id = Column(String, nullable=False, index=True)
    client_order_id = Column(String, unique=True, nullable=False)
    exchange_order_id = Column(String)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    stop_price = Column(Float)
    limit_price = Column(Float)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KillSwitchEvent(Base):
    __tablename__ = "kill_switch_events"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    reason = Column(String, nullable=False)
    actor = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=utc_now, index=True)


class BacktestRun(Base):
    """Registro auditável de uma execução histórica, sem promover modelos automaticamente."""
    __tablename__ = "backtest_runs"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, default="1h")
    mode = Column(String, nullable=False, default="historical")
    dataset_path = Column(String, nullable=False)
    dataset_sha256 = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="completed")
    initial_capital = Column(Float)
    final_capital = Column(Float)
    total_pnl = Column(Float)
    return_pct = Column(Float)
    sharpe_ratio = Column(Float)
    maximum_drawdown = Column(Float)
    trades_executed = Column(Integer, default=0)
    configuration_json = Column(JSON)
    result_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now, index=True)


class DecisionSnapshot(Base):
    """Contexto imutável de uma decisão para paridade live, shadow e replay."""
    __tablename__ = "decision_snapshots"
    __table_args__ = (Index("ix_decision_snapshots_symbol_timeframe_observed_at", "symbol", "timeframe", "observed_at"),)
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, default="1h")
    mode = Column(String, nullable=False, default="shadow")
    observed_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    dataset_path = Column(String)
    dataset_sha256 = Column(String)
    feature_hash = Column(String)
    action = Column(String, nullable=False, default="hold")
    candidate_action = Column(String, nullable=False, default="hold")
    confidence = Column(Float, default=0.0)
    gate_status = Column(String, nullable=False, default="blocked")
    before_context_json = Column(JSON, nullable=False, default=dict)
    after_context_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now, index=True)


class MarketCandle(Base):
    """Candle OHLCV imutável; a chave composta impede duplicatas por origem temporal."""
    __tablename__ = "market_candles"
    __table_args__ = (
        Index("ix_market_candles_symbol_timeframe_timestamp", "symbol", "timeframe", "timestamp"),
    )
    symbol = Column(String(64), primary_key=True, nullable=False)
    timeframe = Column(String(16), primary_key=True, nullable=False)
    timestamp = Column(DateTime, primary_key=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    source = Column(String(64), nullable=False, default="unknown")
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ModelRegistry(Base):
    """Metadados auditáveis de artefatos; não promove modelos nem altera o gate hold."""
    __tablename__ = "model_registry"
    id = Column(Integer, primary_key=True)
    model_name = Column(String(128), nullable=False)
    version = Column(String(128), nullable=False, unique=True)
    artifact_sha256 = Column(String(64), nullable=False)
    dataset_sha256 = Column(String(64))
    metrics_oos_json = Column(JSON, nullable=False, default=dict)
    training_config_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="candidate")
    registered_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    __table_args__ = (Index("ix_model_registry_name_status", "model_name", "status"),)


class ModelMetric(Base):
    """Métricas versionadas por split/regime para acompanhar avaliação fora da amostra."""
    __tablename__ = "model_metrics"
    id = Column(Integer, primary_key=True)
    model_version = Column(String(128), ForeignKey("model_registry.version", ondelete="RESTRICT"), nullable=False)
    metric_name = Column(String(64), nullable=False)
    regime = Column(String(64), nullable=False, default="all")
    split = Column(String(32), nullable=False, default="oos")
    metric_value = Column(Float, nullable=False)
    measured_at = Column(DateTime, nullable=False, default=utc_now)
    __table_args__ = (Index("ix_model_metrics_version_regime_time", "model_version", "regime", "measured_at"),)


class DataGap(Base):
    """Gap/staleness de feed registrado sem autorizar sinais com dados inválidos."""
    __tablename__ = "data_gaps"
    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    symbol = Column(String(64), nullable=False)
    timeframe = Column(String(16), nullable=False)
    gap_start = Column(DateTime, nullable=False)
    gap_end = Column(DateTime)
    detected_at = Column(DateTime, nullable=False, default=utc_now)
    status = Column(String(32), nullable=False, default="open")
    details_json = Column(JSON, nullable=False, default=dict)
    __table_args__ = (Index("ix_data_gaps_symbol_timeframe_detected_at", "symbol", "timeframe", "detected_at"),)


class AdminAuditLog(Base):
    """Registro aditivo de ações administrativas; não guarda segredos ou credenciais."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    actor = Column(String(128), nullable=False)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128))
    correlation_id = Column(String(128))
    details_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    __table_args__ = (Index("ix_audit_log_actor_created_at", "actor", "created_at"),)
